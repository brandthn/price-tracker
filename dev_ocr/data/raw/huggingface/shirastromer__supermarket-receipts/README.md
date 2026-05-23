---
license: apache-2.0
dataset_info:
  features:
  - name: image
    dtype: image
  - name: receiptId
    dtype: string
  - name: text
    dtype: string
  splits:
  - name: train
    num_bytes: 245909927.34375
    num_examples: 153
  - name: test
    num_bytes: 62682922.65625
    num_examples: 39
  download_size: 305634002
  dataset_size: 308592850.0
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
  - split: test
    path: data/test-*
---
