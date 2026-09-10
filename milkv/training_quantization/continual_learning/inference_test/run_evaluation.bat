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
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_1 --gate ../../dataset/classification_fixed/test/gate --outfile coll1
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 2 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_2 --gate ../../dataset/classification_fixed/test/gate --outfile coll2
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 3 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_3 --gate ../../dataset/classification_fixed/test/gate --outfile coll3
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 4 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_4 --gate ../../dataset/classification_fixed/test/gate --outfile coll4
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 5 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_5 --gate ../../dataset/classification_fixed/test/gate --outfile coll5
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 6 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_6 --gate ../../dataset/classification_fixed/test/gate --outfile coll6
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 7 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_7 --gate ../../dataset/classification_fixed/test/gate --outfile coll7
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 8 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_8 --gate ../../dataset/classification_fixed/test/gate --outfile coll8
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation collision 9 ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset_training/collisione_9 --gate ../../dataset/classification_fixed/test/gate --outfile coll9
if errorlevel 1 goto :error

echo ===========================================
echo === evaluation original dataset ===
echo ===========================================
python3 evaluate_model.py --cfg ../config.json --model ../../throwaway_models/original_model2.pt ../../throwaway_models/collisione_1_finetune.pt ../../throwaway_models/collisione_2_finetune.pt ../../throwaway_models/collisione_3_finetune.pt --model_label original_model finetune_coll1 finetune_coll2 finetune_coll3 --no_gate ../../dataset/classification_fixed/test/no_gate --gate ../../dataset/classification_fixed/test/gate --outfile original_dataset
if errorlevel 1 goto :error

echo ===========================================
echo === PLOTS macro avarage e F1 ===
echo ===========================================
python3 .\plot_macro_avarage.py --src ../experiments_progressive_collision1_random/
if errorlevel 1 goto :error
python3 .\plot_F1_macro.py --src ../experiments_progressive_collision1_random/


goto :eof

:error
echo.
echo [ERRORE] Uno dei comandi ha fallito. Controlla l'output sopra.
exit /b 1
