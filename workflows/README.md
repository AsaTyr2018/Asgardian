# Asgardian ComfyUI workflows

Die beiden Dateien sind bereinigte API-Workflows aus der realen ComfyUI-Historie
from a ComfyUI-compatible engine snapshot. They are not UI workflow exports.

- `qwen-text-to-image.api.json`: initiale Generierung ohne Quellbild
- `qwen-image-edit.api.json`: Bearbeitung mit `LoadImage` und
  `TextEncodeQwenImageEditPlus`

Der Backend-Adapter darf ausschließlich folgende Platzhalter ersetzen:

- `${PROMPT}`
- `${NEGATIVE_PROMPT}`
- `${SEED}`
- `${SOURCE_IMAGE}` (nur Image Edit)
- `${OUTPUT_PREFIX}`

Node-Typen, Links und Modellnamen sind nicht durch den Browser veränderbar. Der
Edit-Workflow nutzt `Qwen-Rapid-AIO-NSFW-v23.safetensors`, acht Schritte,
`sa_solver`, Scheduler `beta`, CFG `1.0` und vorläufig Denoise `1.0`. Der
historische Graph enthielt `0.4`; der kontrollierte Test vom 2026-07-15 zeigte
jedoch, dass dieser Qwen-Graph sein Quellbild über die Edit-Konditionierung und
nicht als Sampler-Latent erhält. Niedrigere Denoise-Werte waren deshalb gerade
nicht originaltreuer. Das Profil bleibt bis zum größeren Golden-Test vorläufig.

Die Vorlagen werden mit `python -m unittest discover -s tests` strukturell
geprüft. Eine spätere bewusste Workflow-Änderung muss Vorlage, Tests und
Phase-0-Messprotokoll gemeinsam aktualisieren.
