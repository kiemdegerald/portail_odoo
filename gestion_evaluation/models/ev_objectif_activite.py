# -*- coding: utf-8 -*-
"""Les activités d'un objectif.

Un objectif est une intention — « fiabiliser la production applicative ».
Ce qui se mesure, ce sont les ACTIVITÉS qu'il recouvre, et chacune porte
le résultat qu'on en attend. C'est la structure de la fiche d'évaluation
de la banque : un objectif, plusieurs activités, un résultat attendu par
activité.

Le résultat attendu se fixe en DÉBUT d'exercice, en même temps que
l'objectif. Ce qui a été réellement atteint, et le taux qui en découle,
se saisiront en fin d'exercice — ils ne sont pas ici.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EvObjectifActivite(models.Model):
    _name = "ev.objectif.activite"
    _description = "Activité d'un objectif"
    _order = "goal_id, sequence, id"

    goal_id = fields.Many2one(
        "hr.appraisal.goal", string="Objectif", required=True,
        ondelete="cascade", index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(
        string="Activité", required=True,
        help="Ce que l'agent doit faire — une action, pas une intention.")
    resultat_attendu = fields.Text(
        string="Résultat attendu",
        help="Ce à quoi on reconnaîtra que l'activité est accomplie. "
             "Se fixe en début d'exercice, avec l'objectif : c'est la "
             "commande passée à l'agent.")

    # Reports de lecture : ils évitent de remonter l'objectif à chaque
    # filtre, et permettent de retrouver les activités d'un exercice.
    employee_id = fields.Many2one(
        related="goal_id.employee_id", string="Agent", store=True,
        index=True, readonly=True)
    ev_periode_id = fields.Many2one(
        related="goal_id.ev_periode_id", string="Période", store=True,
        index=True, readonly=True)
    ev_exercice = fields.Char(
        related="goal_id.ev_exercice", string="Exercice", store=True,
        readonly=True)

    @api.constrains("name")
    def _check_name(self):
        for activite in self:
            libelle = (activite.name or "").strip()
            if not libelle:
                raise ValidationError(_("Une activité doit avoir un libellé."))
            # Une activité s'énonce en une phrase. Sans borne, un
            # copier-coller malheureux déforme durablement la fiche.
            if len(libelle) > 300:
                raise ValidationError(_(
                    "Le libellé de l'activité est trop long (%(n)s caractères "
                    "pour %(max)s au maximum). Résumez-le, et mettez le "
                    "détail dans le résultat attendu.",
                    n=len(libelle), max=300))

    @api.constrains("name", "goal_id")
    def _check_doublon(self):
        """Deux activités identiques sous le même objectif n'ont pas de
        sens, et un double clic sur « Ajouter » suffisait à en créer
        plusieurs."""
        for activite in self:
            if self.search_count([
                ("id", "!=", activite.id),
                ("goal_id", "=", activite.goal_id.id),
                ("name", "=ilike", (activite.name or "").strip()),
            ]):
                raise ValidationError(_(
                    "« %s » figure déjà parmi les activités de cet objectif.",
                    activite.name))
