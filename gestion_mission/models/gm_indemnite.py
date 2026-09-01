# -*- coding: utf-8 -*-
"""Le détail de l'indemnité d'un missionnaire, poste par poste.

Une ligne par membre et par type d'indemnité : restauration, hébergement,
ce que la banque a configuré. Les lignes sont GÉNÉRÉES à la soumission, à
partir du barème (zone × catégorie × type), et figées là — même
philosophie que la photo du circuit : les valideurs statuent sur des
montants qui ne bougeront plus, même si le barème change ensuite.
"""
from odoo import api, fields, models


class GmMissionIndemnite(models.Model):
    _name = "gm.mission.indemnite"
    _description = "Indemnité d'un missionnaire, par type"
    _order = "membre_id, sequence, id"

    mission_id = fields.Many2one(
        "gm.mission", string="Mission", required=True,
        ondelete="cascade", index=True)
    membre_id = fields.Many2one(
        "gm.mission.membre", string="Missionnaire", required=True,
        ondelete="cascade", index=True)
    # PAS de copie stockée de l'agent ici. Un champ `related` STOCKÉ vers
    # le membre rendait toute suppression de mission impossible : la
    # cascade efface les membres, puis Odoo tente de recalculer ce champ
    # en relisant un membre qui n'existe plus — « Enregistrement
    # inexistant ou supprimé (gm.mission.membre) ». Le membre est déjà
    # accessible par `membre_id`, cette copie n'apportait rien.
    type_id = fields.Many2one(
        "gm.indemnite.type", string="Type d'indemnité", required=True,
        ondelete="restrict")
    sequence = fields.Integer(string="Ordre", default=10)

    # --- Photo prise à la soumission -----------------------------------
    # Saisissables en brouillon : c'est ainsi qu'on donne une indemnité à
    # un chauffeur, qui n'a ni classification ni barème. Pour les agents,
    # la soumission écrase de toute façon ces valeurs par celles du
    # barème. La vue verrouille la saisie dès que la mission est partie.
    jours = fields.Float(
        string="Jours", default=1.0,
        help="Nombre de jours retenus pour cette indemnité.")
    montant_jour = fields.Monetary(
        string="Montant / jour",
        help="Taux appliqué. Pour un agent, il vient du barème à la "
             "soumission ; pour un chauffeur, il se saisit.")
    montant = fields.Monetary(
        string="Montant", compute="_compute_montant",
        store=True, readonly=False,
        help="Jours × montant par jour. Modifiable si le calcul ne "
             "convient pas.")

    @api.depends("jours", "montant_jour")
    def _compute_montant(self):
        for ligne in self:
            ligne.montant = (ligne.jours or 0.0) * (ligne.montant_jour or 0.0)
    currency_id = fields.Many2one(
        # STOCKÉE : au moment d'écrire un champ monétaire, Odoo relit
        # sa devise. Non stockée, elle était relue sur la mission —
        # déjà effacée pendant une suppression en cascade, d'où
        # « Enregistrement inexistant ou supprimé ».
        related="mission_id.currency_id", string="Devise", store=True)

    def name_get(self):
        return [(l.id, "%s — %s" % (l.membre_id.nom_affiche or "",
                                    l.type_id.name or "")) for l in self]
