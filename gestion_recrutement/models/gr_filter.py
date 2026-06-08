# -*- coding: utf-8 -*-
"""Moteur de questions de filtre paramétrables.

Modèles :

* ``gr.filter.question``        : une question rattachée à une offre.
* ``gr.filter.rule``            : une règle « SI <condition> ALORS <action> »
                                        d'une question (plusieurs par question).
* ``gr.filter.option`` : les choix d'une question « choix multiple ».
* ``gr.applicant.answer``    : la réponse d'un candidat (historisée).

Toute la logique (sérialisation vers le site, correspondance d'une réponse
avec une règle) vit ici pour rester testable et découplée du contrôleur.
"""
from odoo import api, fields, models

from odoo.addons.gestion_recrutement.const import (
    ANSWER_TYPE_CHOICE,
    ANSWER_TYPE_NUMBER,
    ANSWER_TYPE_TEXT,
    ANSWER_TYPE_YES_NO,
    ANSWER_TYPES,
    NUM_OP_EQ,
    NUM_OP_GE,
    NUM_OP_GT,
    NUM_OP_LE,
    NUM_OP_LT,
    NUMBER_OPERATORS,
    RULE_ACTION_BLOCK,
    RULE_ACTION_NONE,
    RULE_ACTIONS,
    TEXT_OPERATORS,
    TXT_OP_CONTAINS,
    TXT_OP_EQ,
    TXT_OP_IS_NOT_SET,
    TXT_OP_IS_SET,
    normalize_yes_no,
)


class GrFilterQuestion(models.Model):
    _name = "gr.filter.question"
    _description = "Question de filtre d'une offre d'emploi"
    _order = "job_id, sequence, id"

    job_id = fields.Many2one(
        "hr.job", string="Offre", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Question", required=True, translate=True)
    answer_type = fields.Selection(
        selection=ANSWER_TYPES, string="Type de réponse",
        required=True, default=ANSWER_TYPE_YES_NO,
    )
    option_ids = fields.One2many(
        "gr.filter.option", "question_id",
        string="Choix possibles",
    )
    is_required = fields.Boolean(string="Obligatoire", default=True)
    active = fields.Boolean(string="Active", default=True)

    # Une question peut porter plusieurs règles (ex. « Non → archiver » et
    # « Oui → placer à l'étape X »). Elles sont évaluées par priorité d'action.
    rule_ids = fields.One2many(
        "gr.filter.rule", "question_id", string="Règles automatiques",
        copy=True,
    )

    def gr_serialize(self):
        """Sérialise la question pour le site (sans exposer les règles)."""
        self.ensure_one()
        return {
            "id": self.id,
            "question": self.name or "",
            "answer_type": self.answer_type,
            "required": self.is_required,
            "options": [
                {"id": opt.id, "label": opt.name}
                for opt in self.option_ids
            ],
        }


class GrFilterRule(models.Model):
    _name = "gr.filter.rule"
    _description = "Règle automatique d'une question de filtre"
    _order = "question_id, sequence, id"

    question_id = fields.Many2one(
        "gr.filter.question", string="Question",
        required=True, ondelete="cascade", index=True,
    )
    # Type de la question (pour afficher le bon champ de condition dans la vue).
    answer_type = fields.Selection(
        related="question_id.answer_type", string="Type de réponse", store=False,
    )
    sequence = fields.Integer(default=10)

    # --- Condition : « SI la réponse ... » (un champ dédié par type) ---
    rule_value_yesno = fields.Selection(
        selection=[("yes", "Oui"), ("no", "Non")], string="Réponse (Oui/Non)",
    )
    rule_value_option_id = fields.Many2one(
        "gr.filter.option", string="Choix déclencheur",
        ondelete="set null",
    )
    rule_number_operator = fields.Selection(
        selection=NUMBER_OPERATORS, string="Comparaison", default=NUM_OP_GE,
    )
    rule_value_number = fields.Float(string="Valeur seuil")
    rule_text_operator = fields.Selection(
        selection=TEXT_OPERATORS, string="Comparaison (texte)",
        default=TXT_OP_CONTAINS,
    )
    rule_value_text = fields.Char(string="Texte déclencheur")

    # --- Action : « ALORS ... » ---
    rule_action = fields.Selection(
        selection=RULE_ACTIONS, string="Action", required=True,
        default=RULE_ACTION_BLOCK,
    )
    rule_stage_id = fields.Many2one(
        "hr.recruitment.stage", string="Étape cible",
        help="Étape appliquée quand l'action est « Placer dans une étape ».",
    )
    rule_summary = fields.Char(
        string="Règle", compute="_compute_rule_summary",
        help="Résumé lisible de la règle.",
    )

    # ------------------------------------------------------------------
    @api.depends(
        "answer_type", "rule_action", "rule_value_yesno", "rule_value_option_id",
        "rule_number_operator", "rule_value_number", "rule_text_operator",
        "rule_value_text", "rule_stage_id",
    )
    def _compute_rule_summary(self):
        actions = dict(RULE_ACTIONS)
        num_ops = dict(NUMBER_OPERATORS)
        txt_ops = dict(TEXT_OPERATORS)
        for rule in self:
            if rule.rule_action == RULE_ACTION_NONE:
                rule.rule_summary = "Aucune action"
                continue
            cond = rule._condition_label(num_ops, txt_ops)
            action = actions.get(rule.rule_action, rule.rule_action)
            if rule.rule_action == "set_stage" and rule.rule_stage_id:
                action = "Placer à l'étape « %s »" % rule.rule_stage_id.name
            rule.rule_summary = "Si %s → %s" % (cond, action)

    def _condition_label(self, num_ops, txt_ops):
        self.ensure_one()
        if self.answer_type == ANSWER_TYPE_YES_NO:
            return "la réponse est « %s »" % (
                "Oui" if self.rule_value_yesno == "yes" else "Non")
        if self.answer_type == ANSWER_TYPE_CHOICE:
            return "le choix est « %s »" % (self.rule_value_option_id.name or "?")
        if self.answer_type == ANSWER_TYPE_NUMBER:
            return "la valeur est %s %s" % (
                num_ops.get(self.rule_number_operator, "?"),
                ("%g" % self.rule_value_number))
        if self.answer_type == ANSWER_TYPE_TEXT:
            op = self.rule_text_operator
            if op in (TXT_OP_IS_SET, TXT_OP_IS_NOT_SET):
                return "le texte %s" % txt_ops.get(op, "?")
            return "le texte %s « %s »" % (
                txt_ops.get(op, "?"), self.rule_value_text or "")
        return "?"

    @staticmethod
    def _to_number(value):
        """Convertit une réponse en nombre (virgule ou point), sinon None."""
        try:
            return float(str(value).replace(",", ".").strip())
        except (TypeError, ValueError):
            return None

    def matches(self, answer_value):
        """Vrai si la réponse du candidat déclenche cette règle.

        La comparaison dépend du type de la question et, pour Nombre/Texte,
        de l'opérateur choisi.
        """
        self.ensure_one()
        if self.rule_action == RULE_ACTION_NONE:
            return False

        atype = self.answer_type
        if atype == ANSWER_TYPE_YES_NO:
            if not self.rule_value_yesno:
                return False
            return normalize_yes_no(answer_value) == self.rule_value_yesno

        if atype == ANSWER_TYPE_CHOICE:
            if not self.rule_value_option_id:
                return False
            given = (answer_value or "").strip().lower()
            target = (self.rule_value_option_id.name or "").strip().lower()
            return bool(given) and given == target

        if atype == ANSWER_TYPE_NUMBER:
            given = self._to_number(answer_value)
            if given is None:
                return False
            target = self.rule_value_number
            op = self.rule_number_operator
            if op == NUM_OP_GE:
                return given >= target
            if op == NUM_OP_GT:
                return given > target
            if op == NUM_OP_LE:
                return given <= target
            if op == NUM_OP_LT:
                return given < target
            if op == NUM_OP_EQ:
                return given == target
            return False

        if atype == ANSWER_TYPE_TEXT:
            given = (answer_value or "").strip()
            op = self.rule_text_operator
            if op == TXT_OP_IS_SET:
                return bool(given)
            if op == TXT_OP_IS_NOT_SET:
                return not given
            target = (self.rule_value_text or "").strip()
            if not target:
                return False
            if op == TXT_OP_CONTAINS:
                return target.lower() in given.lower()
            if op == TXT_OP_EQ:
                return given.lower() == target.lower()
            return False

        return False


class GrFilterOption(models.Model):
    _name = "gr.filter.option"
    _description = "Choix d'une question de filtre"
    _order = "question_id, sequence, id"

    question_id = fields.Many2one(
        "gr.filter.question", string="Question",
        required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Libellé du choix", required=True, translate=True)


class GrApplicantAnswer(models.Model):
    _name = "gr.applicant.answer"
    _description = "Réponse d'un candidat à une question de filtre"
    _order = "applicant_id, id"

    applicant_id = fields.Many2one(
        "hr.applicant", string="Candidature",
        required=True, ondelete="cascade", index=True,
    )
    question_id = fields.Many2one(
        "gr.filter.question", string="Question", ondelete="set null",
    )
    # Instantané du libellé au moment de la réponse (traçabilité même si la
    # question est modifiée ou supprimée par la suite).
    question_text = fields.Char(string="Question posée", readonly=True)
    answer_value = fields.Char(string="Réponse", readonly=True)
