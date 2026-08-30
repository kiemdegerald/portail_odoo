# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    # Le signataire des documents de mission. Ce n'est PAS toujours le
    # Directeur Général : intérim, délégation de signature, ou une
    # organisation où un autre responsable signe. Le nom ET la fonction
    # se règlent donc tous les deux.
    gm_dg_name = fields.Char(
        string="Nom du signataire",
        help="Imprimé au-dessus de la fonction dans le bloc signature de "
             "l'ordre de mission et de la fiche de décompte. Laisser vide "
             "pour n'imprimer que la fonction.")
    gm_dg_fonction = fields.Char(
        string="Fonction du signataire",
        help="Imprimée sous le nom dans le bloc signature. Laissée vide, "
             "rien n'est imprimé.")

    # --- Fiche d'imputation comptable (paramétrable : les intitulés et
    #     les comptes varient selon le service émetteur et l'organisation)
    gm_imput_service = fields.Char(
        string="Service émetteur (imputation)", default="BADF / SCH",
        help="En-tête de la fiche d'imputation, sous le nom de la banque "
             "(ex. « BADF / SCH » ou « BADF / DCH »).")
    gm_imput_visa = fields.Char(
        string="Libellé du visa", default="VISA DU SERVICE DU CAPITAL HUMAIN",
        help="Mention de visa imprimée en bas de la fiche d'imputation.")
    gm_imput_agence_siege = fields.Char(
        string="Code agence du siège", default="01000",
        help="Code agence porté par la ligne de charge (débit).")
    gm_imput_compte_charge = fields.Char(
        string="Compte de charge (perdiems)", default="62261000001-78")
    gm_imput_libelle_charge = fields.Char(
        string="Intitulé du compte de charge",
        default="FRAIS DE MISSION DU PERSONNEL")
    gm_imput_compte_justifier = fields.Char(
        string="Compte des frais à justifier", default="35124100001-89")
    gm_imput_libelle_justifier = fields.Char(
        string="Intitulé du compte à justifier",
        default="FRAIS DE MISSION A JUSTIFIER PERS")
