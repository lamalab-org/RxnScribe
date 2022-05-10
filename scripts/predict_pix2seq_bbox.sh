#!/bin/bash

NUM_NODES=1
NUM_GPUS_PER_NODE=4

BATCH_SIZE=64
ACCUM_STEP=1

DATESTR=$(date +"%m-%d-%H-%M")
PIX2SEQ_CKPT=./ckpts/checkpoint_e299_ap370.pth
SAVE_PATH=output/pix2seq_bbox_noise32
mkdir -p ${SAVE_PATH}

set -x
#NCCL_P2P_DISABLE=1
#PL_TORCH_DISTRIBUTED_BACKEND=gloo
NCCL_P2P_DISABLE=1 python main.py \
    --data_path preprocess \
    --image_path preprocess/images \
    --save_path $SAVE_PATH \
    --test_file all.json \
    --formats bbox \
    --input_size 1333 \
    --pix2seq \
    --pix2seq_ckpt ${PIX2SEQ_CKPT} \
    --rand_target \
    --augment --add_noise \
    --lr 1e-4 \
    --epochs 400 --eval_per_epoch 5 \
    --warmup 0.05 \
    --label_smoothing 0.1 \
    --batch_size $((BATCH_SIZE / NUM_GPUS_PER_NODE / ACCUM_STEP)) \
    --gradient_accumulation_steps ${ACCUM_STEP} \
    --do_test --no_eval \
    --gpus $NUM_GPUS_PER_NODE  #  2>&1  | tee $SAVE_PATH/log_${DATESTR}.txt
