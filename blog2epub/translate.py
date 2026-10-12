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


def translate_one(source_md, source_name, model="", timeout=900, lang="fr"):
    """Traduit un Markdown et renvoie (markdown, titre traduit ou None)."""
    if not available():
        raise TranslationError("CLI opencode introuvable (OPENCODE=%s)" % OPENCODE)
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "source.md")
        with open(src_path, "w", encoding="utf-8") as handle:
            handle.write(source_md)
        cmd = [OPENCODE, "run", "--auto", "--format", "default",
               "-f", src_path, PROMPT.format(source=source_name)]
        if model:
            cmd[1:1] = ["--model", model]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TranslationError("délai dépassé après %ds" % timeout) from exc
    if result.returncode != 0:
        raise TranslationError("opencode a échoué (%d) : %s"
                              % (result.returncode, (result.stderr or "").strip()[:200]))
    body = _strip_preamble(result.stdout)
    if len(body.split()) < max(20, len(source_md.split()) // 4):
        raise TranslationError("sortie trop courte pour être une traduction")
    title = None
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', result.stdout.strip(), re.S)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                if key.strip() == "title":
                    title = value.strip().strip('"').strip("'")
    return body, title


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