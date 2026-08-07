import os
from pathlib import Path  # (qui non usato direttamente, ma spesso serve nei caller)
import torch
import torch.nn as nn
import torch.nn.functional as F

# =============================================================================
#  compat.py
# =============================================================================
# Questo file contiene “utility” comuni usate in tutta la pipeline:
#   1) scelta device + impostazioni di determinismo (set_device)
#   2) caricamento modello da checkpoint (load_model)
#   3) congelare/scongelare parametri dell’encoder (freeze_encoder_params)
#   4) estrarre un “latent” interno dal modello (extract_latent)
#   5) fare forward dal latent fino all’output (forward_from_latent)
#
# Output tipico del modello:
#   - GateClassifier restituisce una probabilità p in [0,1] (sigmoid)
#   - shape tipica: [B,1] oppure [B] dopo view(-1)
# =============================================================================


# ---- Device / determinismo -------------------------------------------------

def set_device(deterministic: bool = False):
    """
    Sceglie il device PyTorch e (opzionale) imposta un comportamento deterministico.

    INPUT
    -----
    deterministic: se True, prova a rendere riproducibili i risultati:
      - imposta CUBLAS_WORKSPACE_CONFIG (per matmul deterministiche su CUDA)
      - disabilita cudnn.benchmark
      - abilita cudnn.deterministic
      - prova torch.use_deterministic_algorithms(True)

    OUTPUT
    ------
    Ritorna un torch.device:
      - "cuda:0" se CUDA è disponibile
      - altrimenti "cpu"

    SIDE EFFECT
    -----------
    - Stampa su stdout il device selezionato e il nome GPU (se CUDA).
    - Modifica variabili globali di PyTorch (backend cudnn) se deterministic=True.
    """
    # Se vogliamo determinismo su CUDA, PyTorch consiglia di settare CUBLAS_WORKSPACE_CONFIG
    # (serve per alcune operazioni GEMM deterministiche).
    if deterministic and "CUBLAS_WORKSPACE_CONFIG" not in os.environ:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

    # Device principale: usa GPU se disponibile
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    print("Using device:", device)

    # Se siamo su GPU, possiamo configurare CUDNN
    if device.type == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

        if deterministic:
            # benchmark=False evita che cuDNN scelga algoritmi “variabili” basati su benchmark runtime
            torch.backends.cudnn.benchmark = False

            # deterministic=True forza algoritmi deterministici dove possibile
            torch.backends.cudnn.deterministic = True

            # In alcune versioni di PyTorch, questo forza ulteriormente il determinismo.
            # Può fallire su versioni vecchie, per questo c’è il try/except.
            try:
                torch.use_deterministic_algorithms(True)
            except Exception:
                pass
        else:
            # benchmark=True può migliorare performance ma rende meno riproducibile (scelta dinamica algoritmi)
            torch.backends.cudnn.benchmark = True

    return device


# ---- Modello: load + funzioni di utilità -----------------------------------

def load_model(ckpt_path: str, device: torch.device, GateClassifierCls):
    """
    Carica un modello GateClassifier da checkpoint .pt e lo porta su `device`.

    Questo progetto supporta 2 formati di checkpoint:
      A) checkpoint "ricco" (dict) con chiave "gate_classifier_state_dict"
         e metadati come num_channels_start e dropout_p.
      B) checkpoint "semplice" (state_dict puro), cioè un dict di tensori direttamente.

    INPUT
    -----
    ckpt_path: path al file .pt
    device: torch.device su cui caricare (cuda/cpu)
    GateClassifierCls: classe del modello (es: GateClassifier)

    OUTPUT
    ------
    Ritorna un'istanza di GateClassifierCls:
      - con i pesi caricati
      - spostata su device
      - in modalità eval() (quindi dropout disattivato, BN in eval)

    NOTE
    ----
    - La funzione NON congela i parametri: quello lo fa freeze_encoder_params().
    - Se il checkpoint contiene metadati (A), inizializza il modello con gli stessi hyperparam.
    """
    ckpt = torch.load(ckpt_path, map_location=device)

    # Caso A: checkpoint in forma dict con state_dict sotto una chiave nota
    if isinstance(ckpt, dict) and "gate_classifier_state_dict" in ckpt:
        # Metadati per ricostruire il modello esattamente come era in training originale
        num_channels_start = ckpt.get("num_channels_start", 4)
        dropout_p = ckpt.get("dropout_p", 0.0)

        # Fallback robusti se valori None
        if num_channels_start is None:
            num_channels_start = 4
        if dropout_p is None:
            dropout_p = 0.0

        # Ricostruzione modello con iperparam salvati
        model = GateClassifierCls(
            num_channels_start=int(num_channels_start),
            dropout_p=float(dropout_p),
        )

        # Pesi veri e propri
        state_dict = ckpt["gate_classifier_state_dict"]

    else:
        # Caso B: il file .pt è direttamente uno state_dict
        model = GateClassifierCls()  # default (es: num_channels_start=4, dropout_p=0.0)
        state_dict = ckpt

    # Carica i pesi dentro il modello
    model.load_state_dict(state_dict)

    # Sposta il modello su device e lo mette in eval
    model.to(device)
    model.eval()
    return model


def freeze_encoder_params(model, freeze=True):
    """
    Congela (o scongela) i parametri del modello, separando:
      - encoder (tutto tranne fully_connected)
      - head fully_connected (sempre trainabile)

    LOGICA
    ------
    - Se freeze=True:
        * fully_connected  -> requires_grad=True (sempre)
        * resto del modello -> requires_grad=False
        * BatchNorm2d dell’encoder -> m.eval() (blocca statistiche BN)
    - Se freeze=False:
        * fully_connected  -> requires_grad=True
        * resto del modello -> requires_grad=True (perché not freeze)

    INPUT
    -----
    model: nn.Module
    freeze: bool

    OUTPUT
    ------
    Nessun ritorno. Modifica model in-place (requires_grad e BN mode).
    """
    # 1) Imposta requires_grad sui parametri
    for name, p in model.named_parameters():
        if name.startswith("fully_connected"):
            # La testa finale resta sempre trainabile
            p.requires_grad = True
        else:
            # Encoder: se freeze=True -> False, se freeze=False -> True
            p.requires_grad = not freeze

    # 2) Se stiamo congelando, blocchiamo anche le BatchNorm dell’encoder in eval mode,
    #    così non aggiornano running_mean/running_var.
    if freeze:
        for name, m in model.named_modules():
            if isinstance(m, nn.BatchNorm2d):
                # Non tocchiamo eventuali BN dentro fully_connected (se esistessero)
                if not name.startswith("fully_connected"):
                    m.eval()


def extract_latent(model, img, tof, tap: str = "pre_fc"):
    """
    Estrae una rappresentazione latente "Z" a un punto interno della rete.

    IDEA
    ----
    Il GateClassifier ha due rami:
      - branch camera (img)
      - branch ToF (tof)
    poi fa merge (concat) e passa in blocchi combinati + flatten + fully_connected.

    tap indica "dove" vuoi fermarti:
      - 'post_merge'  : subito dopo torch.cat((x,y), dim=1)
      - 'post_comb1'  : dopo combined_block_1
      - 'post_comb2'  : dopo combined_block_2 (prima del flatten)
      - 'pre_fc'      : dopo il flatten (input della fully_connected)

    INPUT
    -----
    img: torch.Tensor [B,1,168,168]
    tof: torch.Tensor [B,1,21,21]
    tap: str

    OUTPUT
    ------
    Ritorna un torch.Tensor Z con shape dipendente dal tap:
      - post_merge/post_comb1/post_comb2: [B, C, H, W]
      - pre_fc:                          [B, D]

    NOTA IMPORTANTE
    --------------
    Questa funzione NON applica fully_connected né sigmoid: ritorna “features” interne.
    """
    # ---------------- Camera branch ----------------
    x = model.conv_camera_layer_1(img)
    x = model.bn_camera_1(x)
    x = model.relu_camera_1(x)
    x = model.camera_pool_1(x)
    x = model.camera_block_1(x)

    # ---------------- ToF branch -------------------
    y = model.tof_layer_1(tof)
    y = model.bn_tof_1(y)
    y = model.relu_tof_1(y)

    # ---------------- Merge ------------------------
    # Concat lungo i canali: produce il tensore combinato
    z = torch.cat((x, y), dim=1)
    if tap == "post_merge":
        return z

    # ---------------- Combined blocks --------------
    z = model.combined_block_1(z)
    if tap == "post_comb1":
        return z

    z = model.combined_block_2(z)
    if tap == "post_comb2":
        return z

    # ---------------- Flatten ----------------------
    # Input “pre_fc”: vettore 2D [B, D]
    z = z.flatten(1)
    return z


def forward_from_latent(model, latent, tap: str = "pre_fc"):
    """
    Fa il forward “dalla rappresentazione latente in poi” fino alla probabilità finale.

    Serve nella modalità latents_only:
      - precomputi Z = extract_latent(...)
      - durante training fai forward_from_latent(model, Z, tap)
      - così NON ricarichi .npy e NON esegui tutta la parte encoder ogni volta

    INPUT
    -----
    latent: torch.Tensor
      - se tap == "pre_fc"     -> [B, D] (già flattened)
      - se tap == "post_comb2" -> [B, C, H, W]
      - se tap == "post_comb1" -> [B, C, H, W]
      - se tap == "post_merge" -> [B, C, H, W]
    tap: string che descrive “che tipo di latent” stai passando

    OUTPUT
    ------
    Ritorna una probabilità (sigmoid) con shape [B,1] (o equivalente),
    cioè lo stesso tipo di output di model(img,tof).
    """
    if tap == "pre_fc":
        # latent è già il vettore flattened, quindi applichiamo solo FC + sigmoid.
        # Usiamo F.linear direttamente con i pesi del layer fully_connected.
        logits = F.linear(latent, model.fully_connected.weight, model.fully_connected.bias)
        return torch.sigmoid(logits)

    elif tap == "post_comb2":
        # latent è una feature map: serve flatten prima della FC
        z = latent.flatten(1)
        logits = F.linear(z, model.fully_connected.weight, model.fully_connected.bias)
        return torch.sigmoid(logits)

    elif tap == "post_comb1":
        # manca combined_block_2, poi flatten, poi FC
        z = model.combined_block_2(latent)
        z = z.flatten(1)
        logits = F.linear(z, model.fully_connected.weight, model.fully_connected.bias)
        return torch.sigmoid(logits)

    elif tap == "post_merge":
        # mancano combined_block_1 e combined_block_2, poi flatten, poi FC
        z = model.combined_block_1(latent)
        z = model.combined_block_2(z)
        z = z.flatten(1)
        logits = F.linear(z, model.fully_connected.weight, model.fully_connected.bias)
        return torch.sigmoid(logits)

    else:
        # Se passi un tap non supportato, è un errore di configurazione/integrazione.
        raise ValueError(f"Unsupported tap: {tap}")
