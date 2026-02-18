# LeRobot Example Datasets

This directory contains minimal usage examples for recording, visualizing and
analyzing LeRobot datasets.

## Prerequisite

```
pip install lerobot
```

## Examples

- **record.py**
  Record a dataset in the LeRobot format from live human data. Currently it only
  captures head and hands position for demonstrations purpose.

  Note: the record.py script always create a new dataset. You must remove
  existing one before running it again:

  ```bash
  rm -rf local_datasets
  ```

- **visualize.py**
  A basic rerun visualizer to plot out the dataset.

- **analyze.py**
  A quick sample to parse and analyze the LeRobot dataset.
