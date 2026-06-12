# -*- coding: utf-8 -*-
"""Hooks d'installation du module Gestion Recrutement.

Corrige le comportement multi-societe : l'utilisateur technique de l'API
(`gr_api_integration`) doit etre membre de TOUTES les societes, sinon la regle
d'enregistrement multi-societe d'Odoo lui masque les offres des societes dont
il n'est pas membre. L'API renverrait alors `{"jobs": []}` pour ces offres
(bug silencieux) et elles n'apparaitraient pas sur le site web.
"""
import logging

from .const import API_USER_XMLID

_logger = logging.getLogger(__name__)


def _attach_api_user_to_all_companies(env):
    """Rattache l'utilisateur technique de l'API a toutes les societes.

    Idempotent : peut etre rejoue sans effet de bord. Silencieux si
    l'utilisateur technique n'existe pas encore (install partielle).
    """
    api_user = env.ref(API_USER_XMLID, raise_if_not_found=False)
    if not api_user:
        _logger.warning(
            "GR: utilisateur technique '%s' introuvable, "
            "rattachement multi-societe ignore.", API_USER_XMLID)
        return
    all_companies = env["res.company"].sudo().search([])
    missing = all_companies - api_user.company_ids
    if missing:
        api_user.sudo().write({"company_ids": [(4, c.id) for c in missing]})
        _logger.info(
            "GR: utilisateur technique '%s' rattache aux societes %s.",
            API_USER_XMLID, missing.ids)


def post_init_hook(env):
    """Execute a l'installation : rattache l'API a toutes les societes."""
    _attach_api_user_to_all_companies(env)
