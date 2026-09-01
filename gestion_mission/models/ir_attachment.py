# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Libellé lisible de la provenance d'un fichier. Sans cela le service RH
# ne voit qu'un nom technique de modèle.
ORIGINES = {
    "gm.mission.indemnite": "Mission — justificatif d'indemnité",
    "gm.mission.frais": "Mission — justificatif de frais",
    "hr.appraisal": "Évaluation — compte-rendu d'entretien",
    "hr.applicant": "Recrutement — dossier de candidature",
}

# Un même modèle peut porter plusieurs pièces de nature différente : la
# clé (modèle, champ) l'emporte alors sur le libellé du modèle seul.
ORIGINES_CHAMP = {
    ("gm.mission", "visa_depart"): "Mission — visa de départ",
    ("gm.mission", "visa_retour"): "Mission — visa de retour",
}

# Champ portant le VRAI nom du fichier, quand il ne suit pas la
# convention Odoo « <champ>_filename ».
NOMS_FICHIER = {
    ("hr.appraisal", "ev_compte_rendu"): "ev_compte_rendu_nom",
}


class IrAttachment(models.Model):
    """Rend les pièces déposées par les agents exploitables par les RH.

    Un champ binaire déclaré ``attachment=True`` est stocké dans
    ``ir.attachment``, mais Odoo nomme la pièce d'après le CHAMP
    (« justificatif ») et non d'après le fichier, et ne dit pas à quel
    enregistrement elle se rattache. On rétablit les deux, en lecture
    seule : c'est ce qui permet une liste unique et compréhensible de
    tout ce que les agents ont téléversé.
    """
    _inherit = "ir.attachment"

    gm_origine = fields.Char(
        string="Provenance", compute="_compute_gm_infos",
        help="Nature du document et module dont il provient.")
    gm_rattachement = fields.Char(
        string="Rattaché à", compute="_compute_gm_infos",
        help="Enregistrement auquel la pièce est attachée : la ligne "
             "d'indemnité, la note de frais, l'évaluation...")
    gm_nom_fichier = fields.Char(
        string="Nom du fichier", compute="_compute_gm_infos",
        help="Nom du fichier tel que l'agent l'a déposé.")

    @api.depends("res_model", "res_id", "res_field", "name")
    def _compute_gm_infos(self):
        for piece in self:
            piece.gm_origine = ORIGINES_CHAMP.get(
                (piece.res_model, piece.res_field),
                ORIGINES.get(piece.res_model, piece.res_model or ""))
            piece.gm_rattachement = ""
            piece.gm_nom_fichier = piece.name
            if not piece.res_model or piece.res_model not in self.env:
                continue
            # sudo() : la liste sert au contrôle RH ; on veut le libellé
            # de l'enregistrement source même si l'utilisateur ne l'ouvre
            # pas lui-même.
            source = self.env[piece.res_model].sudo().browse(
                piece.res_id).exists()
            if not source:
                continue
            piece.gm_rattachement = source.display_name or ""
            if not piece.res_field:
                continue
            champ = NOMS_FICHIER.get(
                (piece.res_model, piece.res_field),
                "%s_filename" % piece.res_field)
            if champ in source._fields:
                piece.gm_nom_fichier = source[champ] or piece.name
