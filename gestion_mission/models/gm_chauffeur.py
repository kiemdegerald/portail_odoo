# -*- coding: utf-8 -*-
"""Répertoire des chauffeurs de mission.

Un chauffeur accompagne la mission, figure sur l'ordre de mission et sur
la fiche de décompte, et reçoit de l'argent — perdiem, carburant, péage.
Il faut donc savoir où le virer.

Deux situations, et le répertoire couvre les deux :

* le chauffeur est **salarié** de la banque — on le rattache à sa fiche
  employé, et son compte vient de là. Une seule source, pas de risque de
  divergence le jour où il change de compte ;
* le chauffeur n'est **pas salarié** — on saisit son compte ici.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GmChauffeur(models.Model):
    _name = "gm.chauffeur"
    _description = "Chauffeur de mission"
    _order = "name"

    name = fields.Char(string="Nom et prénom", required=True)
    fonction = fields.Char(
        string="Fonction", default="Chauffeur",
        help="Imprimée sur l'ordre de mission, en face du nom.")
    employee_id = fields.Many2one(
        "hr.employee", string="Fiche employé", ondelete="set null",
        help="À renseigner si le chauffeur est salarié de la banque. Son "
             "compte bancaire est alors lu sur sa fiche : on ne le saisit "
             "pas deux fois, et il ne peut pas diverger.")
    numero_compte = fields.Char(
        string="N° de compte",
        help="Compte sur lequel virer ses indemnités. Inutile si une fiche "
             "employé est rattachée — le compte en vient.")
    compte_effectif = fields.Char(
        string="Compte retenu", compute="_compute_compte_effectif",
        help="Le compte réellement utilisé par la fiche d'imputation.")
    telephone = fields.Char(string="Téléphone")
    note = fields.Text(string="Notes")
    company_id = fields.Many2one(
        "res.company", string="Société",
        default=lambda self: self.env.company,
        help="Vide = chauffeur disponible pour toutes les sociétés.")
    active = fields.Boolean(default=True)

    @api.depends("employee_id", "numero_compte")
    def _compute_compte_effectif(self):
        """La fiche employé fait foi : c'est elle que la paie tient à jour."""
        for chauffeur in self:
            compte = False
            if chauffeur.employee_id:
                compte = chauffeur.employee_id.sudo(
                ).bank_account_id.acc_number
            chauffeur.compte_effectif = compte or chauffeur.numero_compte

    @api.constrains("employee_id", "numero_compte")
    def _check_compte(self):
        """On ne bloque pas la création — un chauffeur peut être enregistré
        avant qu'on connaisse son compte. Mais on refuse le silence : soit
        une fiche employé, soit un compte saisi."""
        for chauffeur in self:
            if not chauffeur.employee_id and not chauffeur.numero_compte:
                raise ValidationError(_(
                    "Renseignez le compte de %s, ou rattachez-le à sa fiche "
                    "employé : sans compte, aucune indemnité ne pourra lui "
                    "être virée.", chauffeur.name or ""))

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "Ce chauffeur est déjà enregistré pour cette société."),
    ]
