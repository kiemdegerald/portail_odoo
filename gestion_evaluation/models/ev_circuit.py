# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Qui agit à une phase du circuit. Le libellé est celui vu par les RH dans
# l'écran de configuration.
ACTEURS = [
    ("agent", "L'agent évalué"),
    ("n1", "Supérieur hiérarchique (N+1)"),
    ("n2", "Supérieur du N+1 (N+2)"),
    ("fixe", "Personne désignée"),
    ("rh", "Service RH"),
]


class EvCircuitPhase(models.Model):
    """CONFIGURATION du circuit d'évaluation (écran RH).

    Liste ordonnée des phases. Au lancement d'une campagne, ces phases sont
    PHOTOGRAPHIÉES sur chaque évaluation (``ev.evaluation.etape``) avec leur
    acteur RÉSOLU à cet instant : modifier cette liste ensuite n'affecte
    jamais les évaluations déjà en route, et la piste d'audit reste fidèle à
    l'époque de l'exercice.
    """
    _name = "ev.circuit.phase"
    _description = "Phase du circuit d'évaluation (configuration)"
    _order = "sequence, id"

    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(
        string="Phase", required=True,
        help="Ex. : Fixation des objectifs, Auto-évaluation, Notation, "
             "Validation, Entretien.")
    acteur = fields.Selection(
        ACTEURS, string="Qui agit", required=True, default="n1",
        help="Rôle attendu à cette phase. Il est résolu en une personne "
             "précise au lancement de la campagne, à partir de la fiche de "
             "l'agent évalué.")
    employee_id = fields.Many2one(
        "hr.employee", string="Personne désignée",
        help="Employé qui agit à cette phase, si l'acteur est une personne "
             "désignée (ex. le DRH pour toutes les évaluations).")
    saisie_notation = fields.Boolean(
        string="Donne accès à la notation", default=True,
        help="Cochée, l'acteur de cette phase peut remplir la grille de "
             "notation pendant qu'elle est en cours. Décochée, il ne fait "
             "que valider ou renvoyer.\n\n"
             "Décochez-la pour la phase de l'agent évalué si la banque ne "
             "veut pas qu'il se note lui-même : sa contribution reste alors "
             "son commentaire et l'entretien.")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = phase commune à toutes les sociétés.")
    active = fields.Boolean(default=True)

    @api.constrains("acteur", "employee_id")
    def _check_acteur(self):
        for phase in self:
            if phase.acteur == "fixe" and not phase.employee_id:
                raise ValidationError(_(
                    "La phase « %s » attend une personne désignée : "
                    "renseignez-la.", phase.name))


class EvEvaluationEtape(models.Model):
    """PHOTO du circuit sur une évaluation : une ligne par phase, figée au
    lancement de la campagne.

    C'est la piste d'audit : qui devait agir, qui a agi, quand, avec quel
    commentaire — quelle que soit l'évolution ultérieure de la configuration.
    Écritures uniquement via les actions de ``hr.appraisal``.
    """
    _name = "ev.evaluation.etape"
    _description = "Étape du circuit d'une évaluation"
    _order = "sequence, id"

    appraisal_id = fields.Many2one(
        "hr.appraisal", string="Évaluation", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(string="Ordre")
    name = fields.Char(string="Phase", required=True)
    acteur = fields.Selection(ACTEURS, string="Rôle attendu", required=True)
    saisie_notation = fields.Boolean(
        string="Donne accès à la notation", default=True,
        help="Photographié au lancement de la campagne, comme le reste du "
             "circuit : modifier la configuration ensuite ne change rien "
             "aux évaluations déjà en route.")
    validator_id = fields.Many2one(
        "hr.employee", string="Acteur attendu",
        help="Résolu au lancement de la campagne. Vide pour une phase "
             "confiée au service RH : n'importe quel gestionnaire peut agir.")
    state = fields.Selection([
        ("waiting", "À venir"),
        ("pending", "En attente"),
        ("done", "Faite"),
        ("skipped", "Sautée"),
    ], string="Statut", default="waiting", required=True)
    skip_reason = fields.Char(string="Motif du saut", readonly=True)
    acted_by_id = fields.Many2one(
        "res.users", string="Traitée par", readonly=True)
    date_action = fields.Datetime(string="Le", readonly=True)
    comment = fields.Text(string="Commentaire")
