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
    gm_dg_fonction = fields.Char(
        related="company_id.gm_dg_fonction", readonly=False)

    # --- Fiche d'imputation comptable (par société) ---
    gm_imput_service = fields.Char(
        related="company_id.gm_imput_service", readonly=False)
    gm_imput_visa = fields.Char(
        related="company_id.gm_imput_visa", readonly=False)
    gm_imput_agence_siege = fields.Char(
        related="company_id.gm_imput_agence_siege", readonly=False)
    gm_imput_compte_charge = fields.Char(
        related="company_id.gm_imput_compte_charge", readonly=False)
    gm_imput_libelle_charge = fields.Char(
        related="company_id.gm_imput_libelle_charge", readonly=False)
    gm_imput_compte_justifier = fields.Char(
        related="company_id.gm_imput_compte_justifier", readonly=False)
    gm_imput_libelle_justifier = fields.Char(
        related="company_id.gm_imput_libelle_justifier", readonly=False)

    # Qui peut INITIER une demande depuis le portail. Stockage explicite
    # "1"/"0" (pas de config_parameter automatique : décocher supprimerait
    # le paramètre et le réglage reviendrait silencieusement à "autorisé").
    gm_portal_employee_can_create = fields.Boolean(
        string="Les employés créent leurs demandes (portail)",
        help="L'employé peut créer et soumettre ses propres demandes de "
             "mission depuis le portail. Décoché : il ne fait que suivre "
             "les demandes créées pour lui.")
    gm_decompte_individuel = fields.Boolean(
        string="Chaque missionnaire ne tire que sa propre ligne",
        help="Coché : depuis le portail, un simple membre télécharge un "
             "« décompte individuel » ne portant que ses montants. Le chef "
             "de mission et les valideurs continuent de recevoir la fiche "
             "complète — ils répondent du dossier et statuent sur le total "
             "du groupe. "
             "Décoché : tout membre voit la fiche complète.")
    gm_visa_exige = fields.Boolean(
        string="Exiger les visas de départ et de retour",
        help="Coché : à la déclaration du retour, le chef de mission doit "
             "joindre le document visé au départ ET celui visé au retour "
             "(feuille de route tamponnée, ordre de mission visé sur "
             "place...). Sans ces deux pièces, le retour ne peut pas être "
             "déclaré. "
             "Décoché : rien ne change, le retour se déclare avec les "
             "seules dates. "
             "Le réglage est PHOTOGRAPHIÉ sur chaque mission à la "
             "soumission : l'activer n'impose rien aux missions déjà "
             "parties, dont personne n'aurait pu faire viser les "
             "documents.")
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
            gm_decompte_individuel=icp.get_param(
                "gm.decompte_individuel", "0") == "1",
            gm_visa_exige=icp.get_param("gm.visa_exige", "0") == "1",
        )
        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("gm.portal_employee_can_create",
                      "1" if self.gm_portal_employee_can_create else "0")
        icp.set_param("gm.portal_chef_can_create",
                      "1" if self.gm_portal_chef_can_create else "0")
        icp.set_param("gm.decompte_individuel",
                      "1" if self.gm_decompte_individuel else "0")
        icp.set_param("gm.visa_exige",
                      "1" if self.gm_visa_exige else "0")
