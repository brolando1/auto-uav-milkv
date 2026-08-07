@echo off
REM Replica di:
REM  - Collisione 1: build + fine-tuning (config_col1.json)
REM  - Collisione 2: build + fine-tuning (config_col2.json)
REM  - Collisione 3: build + fine-tuning (config_col3.json)
REM  - Solo build per config_col4.json

REM Vai nella cartella dello script
cd /d "%~dp0"

setlocal ENABLEDELAYEDEXPANSION

echo ===========================================
echo === evaluation collision 1 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_0_finetune.pt --model_label original_model finetune_coll1 --no_gate ../../collision_dataset/train/collisione_0 --gate ../../original_dataset/test/gate --outfile coll1
if errorlevel 1 goto :error


goto :eof

:error
echo.
echo [ERRORE] Uno dei comandi ha fallito. Controlla l'output sopra.
exit /b 1
