---
dataset_info:
  features:
  - name: image
    dtype: image
  - name: ground_truth
    dtype: string
  splits:
  - name: train
    num_bytes: 280673107.2
    num_examples: 1800
  - name: test
    num_bytes: 15578492.9
    num_examples: 100
  - name: validation
    num_bytes: 15593664.9
    num_examples: 100
  download_size: 309564410
  dataset_size: 311845264.99999994
task_categories:
- table-to-text
language:
- en
tags:
- finance
size_categories:
- 1K<n<10K
---
# Dataset Card for "fake-w2-us-tax-form-dataset"

This is a dataset of synthetically generated US Tax Return W2 Forms, with generated fake data such as names, ids, dates and addresses. Only real city, state and zipcodes have been used.

This dataset is created from the existing public [Fake W-2 (US Tax Form) Dataset](https://www.kaggle.com/datasets/mcvishnu1/fake-w2-us-tax-form-dataset) dataset for use with 
🤗