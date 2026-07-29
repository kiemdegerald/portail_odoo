# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    gm_dg_name = fields.Char(
        string="Nom du Directeur Général",
        help="Imprimé au-dessus de « Directeur Général » dans le bloc "
             "signature de l'ordre de mission et de la fiche de décompte. "
             "Laisser vide pour n'imprimer que la fonction.")
