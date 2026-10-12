"""Traduction automatique via le CLI opencode.

Le modèle par défaut est celui configuré dans opencode ; --model permet de le
surcharger. Un article déjà traduit dans fr/ n'est jamais réécrit.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile

OPENCODE = os.environ.get("BLOG2EPUB_OPENCODE") or shutil.which("opencode") or \
    os.path.expanduser("~/.opencode/bin/opencode")

PROMPT = """\
Traduis en français le billet de blog ci-dessous, joint en fichier source.

Contraintes :
- Respecte exactement la structure Markdown : titres (##), listes, citations (>),
  blocs de code (```), liens [texte](url) et images ![alt](src). Ne réécris pas les URL.
- Traduis uniquement le texte visible. Laisse intacts : les URL, les noms de fichiers,
  les commandes, les identifiants, les noms propres de logiciels et de projets.
- Commence le fichier par un bloc de métadonnées :
  ---
  title: "titre traduit"
  ---
  puis une ligne vide, puis la traduction.
- Ton : tutoiement, phrases courtes, registre de l'auteur. Aucun commentaire,
  aucune explication, pas de préambule : uniquement le fichier markdown.
- Si un passage est technique et obscur, garde le terme anglais plutôt que d'inventer.

Fichier source : {source}
"""


class TranslationError(Exception):
    pass


def available():
    return bool(OPENCODE) and os.path.exists(OPENCODE)


def _strip_preamble(text):
    """Retire un éventuel préambule du modèle et les fences markdown."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    return "\n".join(lines).strip()


def chunk_markdown(md, max_words=420):
    """Découpe un Markdown aux frontières de sections, sans casser un bloc.

    Les modèles free-tier tronquent les longues sorties : traduire par sections
    est nettement plus fiable que tout d'un bloc.
    """
    blocks = md.strip().split("\n\n")
    chunks, current, words = [], [], 0
    for block in blocks:
        count = len(block.split())
        is_heading = block.lstrip().startswith("#")
        if current and words + count > max_words and not is_heading:
            chunks.append("\n\n".join(current))
            current, words = [], 0
        if count > max_words * 2:
            # bloc géant (long listing) : on le laisse seul dans son chunk
            if current:
                chunks.append("\n\n".join(current))
                current, words = [], 0
            chunks.append(block)
            continue
        current.append(block)
        words += count
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _extract_text(output):
    """`opencode run --format json` sort un flux JSONL d'événements.

    On n'en garde que les parties de texte ; en repli, on nettoie la sortie
    brute des séquences de progression et des codes couleur.
    """
    pieces = []
    for line in output.split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            pieces.append(part["text"])
    if pieces:
        return "\n".join(pieces)
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return "\n".join(l for l in cleaned.split("\n")
                     if not l.strip().startswith("> build"))


def _run_once(source_md, source_name, model, timeout, chunk_index=None):
    prompt = PROMPT.format(source=source_name)
    if chunk_index is not None:
        prompt = ("Tu traduis la section %d d'un billet. Traduis uniquement le contenu "
                  "du fichier joint, sans titre de billet ni commentaire.\n\n%s"
                  % (chunk_index, prompt))
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "source.md")
        with open(src_path, "w", encoding="utf-8") as handle:
            handle.write(source_md)
        cmd = [OPENCODE, "run", "--auto", "--format", "json"]
        if model:
            cmd += ["--model", model]
        cmd += ["-f", src_path, prompt]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TranslationError("délai dépassé après %ds" % timeout) from exc
    if result.returncode != 0:
        message = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr or "")
        message = " ".join(message.split())
        raise TranslationError("opencode a échoué : %s" % message[:160])
    return _extract_text(result.stdout)


def _title_of(output):
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", output.strip(), re.S)
    if not match:
        return None
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip() == "title":
                return value.strip().strip('"').strip("'")
    return None


def translate_one(source_md, source_name, model="", timeout=900, lang="fr",
                  attempts=2, on_progress=None, single_shot=2500, chunk_words=600):
    """Traduit un Markdown et renvoie (markdown, titre traduit ou None).

    `model` peut être une liste de modèles : le premier qui répond correctement
    est retenu, ce qui évite de rester bloqué sur un modèle déprécié.
    """
    if not available():
        raise TranslationError("CLI opencode introuvable (OPENCODE=%s)" % OPENCODE)
    models = [m for m in (model if isinstance(model, (list, tuple)) else [model]) if m]
    if not models:
        models = [""]

    words = len(source_md.split())
    if words <= single_shot:
        # En dessous du seuil, un jeton unique donne un bien meilleur rendu que
        # des sections : le modèle dispose du contexte et garde titres et liens.
        chunks = [source_md]
    else:
        chunks = chunk_markdown(source_md, chunk_words)
    total = len(chunks)
    pieces, title, last_error = [], None, None
    for index, chunk in enumerate(chunks, start=1):
        done = False
        for candidate in models:
            for attempt in range(attempts):
                try:
                    output = _run_once(chunk, source_name, candidate, timeout,
                                       index if total > 1 else None)
                except TranslationError as exc:
                    last_error = exc
                    continue
                body = _strip_preamble(output)
                if len(body.split()) < max(10, len(chunk.split()) // 3):
                    last_error = TranslationError(
                        "section %d/%d : sortie trop courte (%d mots pour %d)"
                        % (index, total, len(body.split()), len(chunk.split())))
                    continue
                if index == 1:
                    title = _title_of(output) or title
                pieces.append(body)
                done = True
                break
            if done:
                break
        if not done:
            raise last_error or TranslationError("traduction impossible")
        if on_progress:
            on_progress(index, total)
    return "\n\n".join(pieces), title


# --------------------------------------------------------------------------
# Contrôle de parité des traductions
# --------------------------------------------------------------------------
EN_FUNCTION_WORDS = (
    "the", "and", "you", "your", "with", "that", "this", "from", "have", "will",
    "which", "they", "been", "were", "their", "there", "about", "would", "could",
    "should", "when", "what", "where", "than", "then", "them", "these", "those",
    "very", "just", "into", "over", "such", "some", "more", "most", "other",
    "because", "while", "after", "before", "again", "being", "does", "doing",
)


def structure_of(md):
    return {
        "titres": len(re.findall(r"^#{1,6}\s", md, re.M)),
        "liens": len(re.findall(r"(?<!\!)\[[^\]]*\]\(", md)),
        "images": len(re.findall(r"!\[[^\]]*\]\(", md)),
        "codes": md.count("```") // 2,
        "citations": len(re.findall(r"^>\s", md, re.M)),
        "puces": len(re.findall(r"^\s*[-*+]\s", md, re.M)),
        "mots": len(md.split()),
    }


def lint(source_md, translated_md):
    """Signale une traduction partielle ou contaminée."""
    issues = []
    src, dst = structure_of(source_md), structure_of(translated_md)
    for key in ("titres", "liens", "images", "codes", "citations", "puces"):
        if src[key] != dst[key]:
            issues.append("%s : source=%d traduction=%d" % (key, src[key], dst[key]))
    ratio = dst["mots"] / max(src["mots"], 1)
    if not (0.75 <= ratio <= 1.4):
        issues.append("longueur suspecte : %d mots source pour %d mots FR"
                      % (src["mots"], dst["mots"]))
    for index, line in enumerate(translated_md.split("\n"), 1):
        suspect = re.findall(r"[^\x00-\x7F -ɏ‐-※€]", line)
        if suspect:
            issues.append("ligne %d : caractères non latins %s"
                          % (index, "".join(sorted(set(suspect)))))
    for pattern in (r"\[Pardon", r"\[Stop\]", r"\[Reprise", r"\{\{", r"\}\}"):
        if re.search(pattern, translated_md):
            issues.append("placeholder de génération résiduel : %s" % pattern)
    for line in translated_md.split("\n"):
        stripped = re.sub(r"`[^`]*`|\[[^\]]*\]\([^)]*\)|https?://\S+", "", line)
        run = 0
        for word in re.findall(r"[A-Za-z']+", stripped.lower()):
            run = run + 1 if word in EN_FUNCTION_WORDS else 0
            if run >= 3:
                issues.append("anglais résiduel : « %s »" % line.strip()[:70])
                break
    return issues


def write_translation(fr_dir, slug, body, title=""):
    os.makedirs(fr_dir, exist_ok=True)
    path = os.path.join(fr_dir, slug + ".md")
    header = "---\ntitle: \"%s\"\n---\n\n" % title if title else ""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header + body.strip() + "\n")
    return path


def read_title(fr_path):
    if not os.path.exists(fr_path):
        return ""
    with open(fr_path, encoding="utf-8") as handle:
        head = handle.read(600)
    match = re.search(r'^---\s*\n(.*?)\n---', head, re.S)
    if match:
        for line in match.group(1).split("\n"):
            if line.strip().startswith("title:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""