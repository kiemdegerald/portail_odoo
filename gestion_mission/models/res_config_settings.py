# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    # Qui peut INITIER une demande depuis le portail. Stockage explicite
    # "1"/"0" (pas de config_parameter automatique : décocher supprimerait
    # le paramètre et le réglage reviendrait silencieusement à "autorisé").
    gm_portal_employee_can_create = fields.Boolean(
        string="Les employés créent leurs demandes (portail)",
        help="L'employé peut créer et soumettre ses propres demandes de "
             "mission depuis le portail. Décoché : il ne fait que suivre "
             "les demandes créées pour lui.")
    gm_portal_chef_can_create = fields.Boolean(
        string="Les chefs créent pour leurs collaborateurs (portail)",
        help="Un supérieur hiérarchique peut créer une demande au nom d'un "
             "de ses collaborateurs directs depuis le portail (brouillon à "
             "compléter par l'agent, ou soumission directe).")

    @api.model
    def get_values(self):
        res = super().get_values()
        icp = self.env["ir.config_parameter"].sudo()
        res.update(
            gm_portal_employee_can_create=icp.get_param(
                "gm.portal_employee_can_create", "1") == "1",
            gm_portal_chef_can_create=icp.get_param(
                "gm.portal_chef_can_create", "1") == "1",
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("gm.portal_employee_can_create",
                      "1" if self.gm_portal_employee_can_create else "0")
        icp.set_param("gm.portal_chef_can_create",
                      "1" if self.gm_portal_chef_can_create else "0")
