import os
import argparse
from typing import List
import PIL
import torch
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg

from .pix2seq import build_pix2seq_model
from .tokenizer import get_tokenizer
from .dataset import make_transforms
from .data import postprocess_reactions, ReactionImageData

from molscribe import MolScribe
from huggingface_hub import hf_hub_download
import easyocr


class RxnScribe:

    def __init__(self, model_path, device=None):
        """
        RxnScribe Interface
        :param model_path: path of the model checkpoint.
        :param device: torch device, defaults to be CPU.
        """
        args = self._get_args()
        args.format = 'reaction'
        states = torch.load(model_path, map_location=torch.device('cpu'))
        if device is None:
            device = torch.device('cpu')
        self.device = device
        self.tokenizer = get_tokenizer(args)
        self.model = self.get_model(args, self.tokenizer, self.device, states['state_dict'])
        self.transform = make_transforms('test', augment=False, debug=False)
        self.molscribe = self.get_molscribe()
        self.ocr_model = self.get_ocr_model()

    def _get_args(self):
        parser = argparse.ArgumentParser()
        # * Backbone
        parser.add_argument('--backbone', default='resnet50', type=str,
                            help="Name of the convolutional backbone to use")
        parser.add_argument('--dilation', action='store_true',
                            help="If true, we replace stride with dilation in the last convolutional block (DC5)")
        parser.add_argument('--position_embedding', default='sine', type=str, choices=('sine', 'learned'),
                            help="Type of positional embedding to use on top of the image features")
        # * Transformer
        parser.add_argument('--enc_layers', default=6, type=int, help="Number of encoding layers in the transformer")
        parser.add_argument('--dec_layers', default=6, type=int, help="Number of decoding layers in the transformer")
        parser.add_argument('--dim_feedforward', default=1024, type=int,
                            help="Intermediate size of the feedforward layers in the transformer blocks")
        parser.add_argument('--hidden_dim', default=256, type=int,
                            help="Size of the embeddings (dimension of the transformer)")
        parser.add_argument('--dropout', default=0.1, type=float, help="Dropout applied in the transformer")
        parser.add_argument('--nheads', default=8, type=int,
                            help="Number of attention heads inside the transformer's attentions")
        parser.add_argument('--pre_norm', action='store_true')
        # Data
        parser.add_argument('--format', type=str, default='reaction')
        parser.add_argument('--input_size', type=int, default=1333)

        args = parser.parse_args([])
        args.pix2seq = True
        args.pix2seq_ckpt = None
        args.pred_eos = True
        return args

    def get_model(self, args, tokenizer, device, model_states):
        def remove_prefix(state_dict):
            return {k.replace('model.', ''): v for k, v in state_dict.items()}

        model = build_pix2seq_model(args, tokenizer[args.format])
        model.load_state_dict(remove_prefix(model_states), strict=False)
        model.to(device)
        model.eval()
        return model

    def get_molscribe(self):
        ckpt_path = hf_hub_download("yujieq/MolScribe", "swin_base_char_aux_1m.pth")
        molscribe = MolScribe(ckpt_path, device=self.device)
        return molscribe

    def get_ocr_model(self):
        reader = easyocr.Reader(['en'], gpu=(self.device.type == 'cuda'))
        return reader

    def predict_images(self, input_images: List, batch_size=16, molscribe=False, ocr=False):
        # images: a list of PIL images
        device = self.device
        tokenizer = self.tokenizer['reaction']
        predictions = []
        for idx in range(0, len(input_images), batch_size):
            batch_images = input_images[idx:idx+batch_size]
            images, refs = zip(*[self.transform(image) for image in batch_images])
            images = torch.stack(images, dim=0).to(device)
            with torch.no_grad():
                pred_seqs, pred_scores = self.model(images, max_len=tokenizer.max_len)
            for i, (seqs, scores) in enumerate(zip(pred_seqs, pred_scores)):
                reactions = tokenizer.sequence_to_data(seqs.tolist(), scores.tolist(), scale=refs[i]['scale'])
                reactions = postprocess_reactions(
                    reactions,
                    image=input_images[i],
                    molscribe=self.molscribe if molscribe else None,
                    ocr=self.ocr_model if ocr else None
                )
                predictions.append(reactions)
        return predictions

    def predict_image(self, image, **kwargs):
        predictions = self.predict_images([image], **kwargs)
        return predictions[0]

    def predict_image_files(self, image_files: List, **kwargs):
        input_images = []
        for path in image_files:
            image = PIL.Image.open(path).convert("RGB")
            input_images.append(image)
        return self.predict_images(input_images, **kwargs)

    def predict_image_file(self, image_file: str, **kwargs):
        predictions = self.predict_image_files([image_file], **kwargs)
        return predictions[0]

    def draw_predictions(self, predictions, image=None, image_file=None):
        results = []
        assert image or image_file
        data = ReactionImageData(predictions=predictions, image=image, image_file=image_file)
        for r in data.pred_reactions:
            fig, ax = plt.subplots(figsize=(10, 10))
            fig.tight_layout(pad=0)
            canvas = FigureCanvasAgg(fig)
            ax.imshow(data.image)
            ax.axis('off')
            r.draw(ax)
            canvas.draw()
            buf = canvas.buffer_rgba()
            results.append(np.asarray(buf))
            plt.close(fig)
        return results
