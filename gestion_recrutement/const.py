# -*- coding: utf-8 -*-
"""Constantes partagees du module Gestion Recrutement.

Centralise les valeurs metier et techniques utilisees a la fois par les
modeles et par le controleur API, afin d'avoir une seule source de verite.
"""

# --- Types de contrat proposes sur le site web (code technique, libelle) ---
CONTRACT_TYPES = [
    ("cdi", "CDI"),
    ("cdd", "CDD"),
    ("freelance", "Freelance"),
    ("stage", "Stage"),
    ("alternance", "Alternance"),
]

# --- Questions de filtre : types de reponse ---
ANSWER_TYPE_YES_NO = "yes_no"
ANSWER_TYPE_CHOICE = "choice"
ANSWER_TYPE_NUMBER = "number"
ANSWER_TYPE_TEXT = "text"
ANSWER_TYPES = [
    (ANSWER_TYPE_YES_NO, "Oui / Non"),
    (ANSWER_TYPE_NUMBER, "Nombre"),
    # Types desactives pour l'instant (code conserve pour reactivation) :
    # (ANSWER_TYPE_CHOICE, "Choix multiple"),
    # (ANSWER_TYPE_TEXT, "Texte court"),
]

# --- Questions de filtre : operateurs de comparaison ---
# Operateurs numeriques (type "Nombre").
NUM_OP_GE = "ge"
NUM_OP_GT = "gt"
NUM_OP_LE = "le"
NUM_OP_LT = "lt"
NUM_OP_EQ = "eq"
NUMBER_OPERATORS = [
    (NUM_OP_GE, "superieur ou egal (>=)"),
    (NUM_OP_GT, "strictement superieur (>)"),
    (NUM_OP_LE, "inferieur ou egal (<=)"),
    (NUM_OP_LT, "strictement inferieur (<)"),
    (NUM_OP_EQ, "egal (=)"),
]
# Operateurs texte (type "Texte court").
TXT_OP_CONTAINS = "contains"
TXT_OP_EQ = "eq"
TXT_OP_IS_SET = "is_set"
TXT_OP_IS_NOT_SET = "is_not_set"
TEXT_OPERATORS = [
    (TXT_OP_CONTAINS, "contient"),
    (TXT_OP_EQ, "est exactement"),
    (TXT_OP_IS_SET, "n'est pas vide"),
    (TXT_OP_IS_NOT_SET, "est vide"),
]

# --- Questions de filtre : actions de regle ---
RULE_ACTION_NONE = "none"
RULE_ACTION_BLOCK = "block"
RULE_ACTION_ARCHIVE = "archive"
RULE_ACTION_SET_STAGE = "set_stage"
RULE_ACTIONS = [
    (RULE_ACTION_NONE, "Aucune"),
    (RULE_ACTION_BLOCK, "Bloquer la candidature (refus immediat)"),
    (RULE_ACTION_ARCHIVE, "Archiver automatiquement la candidature"),
    (RULE_ACTION_SET_STAGE, "Placer dans une etape precise"),
]
# Priorite d'application si plusieurs regles se declenchent.
RULE_ACTION_PRIORITY = {
    RULE_ACTION_BLOCK: 3,
    RULE_ACTION_ARCHIVE: 2,
    RULE_ACTION_SET_STAGE: 1,
    RULE_ACTION_NONE: 0,
}

# Synonymes normalises vers les valeurs canoniques oui/non.
YES_SYNONYMS = frozenset({"yes", "oui", "true", "1", "y", "o"})
NO_SYNONYMS = frozenset({"no", "non", "false", "0", "n"})

# --- Tracabilite de l'origine des candidatures ---
SOURCE_CHANNEL_WEBSITE = "website"

# --- Contraintes sur les pieces jointes (CV, lettre de motivation) ---
ALLOWED_DOC_MIMETYPES = frozenset({
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})
MAX_DOC_SIZE = 5 * 1024 * 1024  # 5 Mo

# --- Anti-spam (limitation par IP sur le depot de candidature) ---
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 60

# --- Cles de parametres systeme (ir.config_parameter) ---
PARAM_API_KEY = "gestion_recrutement.api_key"
PARAM_ENABLED = "gestion_recrutement.enabled"
PARAM_CORS_ORIGIN = "gestion_recrutement.cors_origin"
PARAM_AUTO_SYNC = "gestion_recrutement.auto_sync"
PARAM_SITE_WEBHOOK_URL = "gestion_recrutement.site_webhook_url"
PARAM_SITE_WEBHOOK_KEY = "gestion_recrutement.site_webhook_key"
PARAM_RATE_LIMIT_MAX = "gestion_recrutement.rate_limit_max"
PARAM_RATE_LIMIT_WINDOW = "gestion_recrutement.rate_limit_window"
# Creation automatique de l'employe quand la candidature atteint une etape
# marquee « Etape d'embauche » (hired_stage), ex. « Signature du contrat ».
PARAM_AUTO_CREATE_EMPLOYEE = "gestion_recrutement.auto_create_employee"

API_USER_XMLID = "gestion_recrutement.user_api"


def normalize_yes_no(value):
    """Normalise une reponse libre vers 'yes' / 'no' / la valeur brute."""
    if value is None:
        return ""
    v = str(value).strip().lower()
    if v in YES_SYNONYMS:
        return "yes"
    if v in NO_SYNONYMS:
        return "no"
    return v
