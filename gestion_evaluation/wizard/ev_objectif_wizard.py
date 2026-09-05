# -*- coding: utf-8 -*-
"""Fixer un objectif depuis le back-office, à la place d'un responsable.

Prévu et assumé : un responsable en congé pendant la période, une
direction sans encadrant nommé. Le service RH saisit à sa place — mais
l'objectif reste attribué au RESPONSABLE de l'agent, pas à la RH : c'est
lui qui répond de la commande passée.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EvObjectifWizard(models.TransientModel):
    _name = "ev.objectif.wizard"
    _description = "Fixer un objectif (service RH)"

    periode_id = fields.Many2one(
        "ev.periode.objectifs", string="Période", required=True,
        readonly=True)
    exercice = fields.Char(related="periode_id.exercice", readonly=True)
    employee_id = fields.Many2one(
        "hr.employee", string="Agent", required=True,
        domain="[('id', 'in', agents_possibles_ids)]",
        help="Agent visé par le ciblage de la période.")
    agents_possibles_ids = fields.Many2many(
        "hr.employee", string="Agents visés",
        compute="_compute_agents_possibles")
    sans_objectif_seulement = fields.Boolean(
        string="Seulement ceux qui n'ont rien", default=True,
        help="Réduit la liste aux agents qui n'ont encore aucun objectif "
             "pour cet exercice — ce sont eux qu'il faut servir.")
    manager_id = fields.Many2one(
        "hr.employee", string="Fixé par",
        help="Le responsable qui passe la commande. Pré-rempli avec le "
             "supérieur hiérarchique de l'agent : c'est lui qui en répond, "
             "même si le service RH saisit à sa place.")
    name = fields.Char(string="Objectif", required=True)
    deadline = fields.Date(string="Échéance")
    description = fields.Html(string="Précisions")

    @api.depends("periode_id", "sans_objectif_seulement")
    def _compute_agents_possibles(self):
        for wiz in self:
            agents = wiz.periode_id._get_employees_cibles() \
                if wiz.periode_id else self.env["hr.employee"]
            if wiz.sans_objectif_seulement and wiz.periode_id:
                agents = agents - wiz.periode_id.goal_ids.employee_id
            wiz.agents_possibles_ids = agents

    @api.onchange("employee_id")
    def _onchange_employee(self):
        self.manager_id = self.employee_id.parent_id

    @api.onchange("sans_objectif_seulement")
    def _onchange_filtre(self):
        if self.employee_id not in self.agents_possibles_ids:
            self.employee_id = False

    def _creer(self):
        self.ensure_one()
        if not self.manager_id:
            raise UserError(_(
                "Indiquez qui fixe cet objectif. Le supérieur hiérarchique "
                "de %s n'est pas renseigné sur sa fiche : choisissez le "
                "responsable, ou faites compléter la fiche employé.",
                self.employee_id.name or ""))
        return self.periode_id._ev_objectif_creer(
            self.employee_id, self.name, echeance=self.deadline,
            description=self.description, manager=self.manager_id)

    def action_confirm(self):
        self._creer()
        return {"type": "ir.actions.act_window_close"}

    def action_confirm_suivant(self):
        """Enregistre et rouvre la fenêtre, vide : on sert plusieurs
        agents d'affilée sans revenir à la période à chaque fois."""
        self._creer()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fixer un objectif"),
            "res_model": "ev.objectif.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_periode_id": self.periode_id.id,
                "default_sans_objectif_seulement":
                    self.sans_objectif_seulement,
            },
        }
