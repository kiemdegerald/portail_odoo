# -*- coding: utf-8 -*-
"""Écran Paramètres > Évaluations : les réglages que la banque arbitre."""
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ev_auto_evaluation_active = fields.Boolean(
        string="L'agent s'auto-évalue",
        help="Coché : l'agent remplit sa propre colonne de la grille, la "
             "publie, et elle sert de point de comparaison à l'entretien.\n\n"
             "Décoché : il n'y a plus d'auto-évaluation du tout — l'agent "
             "ne voit pas de grille à remplir, et seule la notation du "
             "responsable compte. Le réglage est lu au LANCEMENT de chaque "
             "campagne : le modifier ne change rien aux campagnes déjà "
             "ouvertes.")

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env["ir.config_parameter"].sudo()
        # Stockage explicite « 1 »/« 0 » : avec `config_parameter`, décocher
        # SUPPRIME le paramètre, et le réglage reviendrait silencieusement à
        # sa valeur par défaut au prochain lancement de campagne.
        res.update(ev_auto_evaluation_active=icp.get_param(
            "ev.auto_evaluation_active", "1") == "1")
        return res

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            "ev.auto_evaluation_active",
            "1" if self.ev_auto_evaluation_active else "0")
