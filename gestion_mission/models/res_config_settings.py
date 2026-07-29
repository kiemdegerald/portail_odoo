# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Écran Paramètres > Missions : regroupe les réglages du module
    (jusqu'ici seulement accessibles via les paramètres système)."""
    _inherit = "res.config.settings"

    gm_avance_pct = fields.Float(
        string="Avance avant départ (%)",
        config_parameter="gm.avance_pct", default=100.0,
        help="Pourcentage du total dû proposé automatiquement comme avance "
             "à la soumission d'une mission (0 à 100). Commun à toutes les "
             "sociétés.")
    gm_dg_name = fields.Char(
        related="company_id.gm_dg_name", readonly=False,
        help="Propre à la société sélectionnée : imprimé dans le bloc "
             "signature des documents de mission.")
