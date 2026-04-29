# Dependency Notes

Active hourly DA stack dependencies:
- `pandas`
- `numpy`
- `scipy`
- `matplotlib`
- `jinja2` for notebook `pandas.Styler` rendering
- `holidays`
- `scikit-learn` for LEAR
- `xgboost` for XGBoost
- `prophet` for Prophet
- `pyarrow` for Parquet prediction storage

Important notebook execution note:
- Heavy-run notebook hooks launch scripts with the active notebook interpreter via `sys.executable`.
- Install optional model packages such as `prophet` into that same interpreter/kernel before running the notebook hook.

Optional:
- `nbformat`; notebooks are stored as plain `.ipynb` files in the repo.

Legacy only:
- `statsmodels` is no longer part of the active DAM stack, but it may still be needed if archived classical-model code is opened historically.

Suggested later installs:

```powershell
.\.venv\Scripts\python.exe -m pip install scikit-learn xgboost prophet nbformat pyarrow
```
