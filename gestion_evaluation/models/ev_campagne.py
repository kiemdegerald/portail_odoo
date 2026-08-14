# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EvCampagne(models.Model):
    """Campagne d'évaluation annuelle.

    Odoo standard raisonne évaluation par évaluation : chaque agent porte sa
    propre date d'anniversaire. La banque, elle, ouvre un EXERCICE pour une
    population, suit son avancement et le clôture. C'est cet objet-là qui
    manque au standard, et que ce modèle apporte.

    La campagne ne remplace pas l'évaluation : elle GÉNÈRE et PILOTE des
    ``hr.appraisal`` standard, qui gardent tout leur comportement natif
    (feedbacks, notation, compétences, entretien, 360°).
    """
    _name = "ev.campagne"
    _description = "Campagne d'évaluation"
    # Lecture ouverte à tout utilisateur interne : l'agent évalué et son
    # manager voient le champ « Campagne » sur leur évaluation, et Odoo doit
    # pouvoir lire l'enregistrement pour l'afficher. Rien de confidentiel n'y
    # figure — ni note, ni appréciation. L'écriture reste aux RH.
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_debut desc, id desc"

    name = fields.Char(
        string="Intitulé", required=True, tracking=True,
        help="Ex. : Évaluation annuelle 2026.")
    exercice = fields.Char(
        string="Exercice", required=True, tracking=True,
        default=lambda self: str(fields.Date.context_today(self).year),
        help="Année de référence de la campagne.")
    company_id = fields.Many2one(
        "res.company", string="Société", required=True,
        default=lambda self: self.env.company)

    # --- Période de la campagne : documentaire, elle borne l'exercice ---
    date_debut = fields.Date(
        string="Ouverture de la campagne", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self),
        help="Date à laquelle l'exercice est ouvert auprès des agents. "
             "Sert de repère : elle n'est pas reportée sur les évaluations.")
    date_fin = fields.Date(
        string="Échéance de la campagne", required=True, tracking=True,
        help="Date à laquelle toutes les évaluations devraient être "
             "terminées. Sert de repère pour le suivi des retards : elle "
             "n'est pas reportée sur les évaluations.")

    # --- Ce qui est réellement posé sur chaque évaluation générée ---
    date_evaluation = fields.Date(
        string="Date d'entretien prévue", required=True, tracking=True,
        help="SEULE date reportée sur les évaluations générées. Chaque "
             "manager peut ensuite l'ajuster individuellement. Odoo la "
             "remplace par la date réelle une fois l'évaluation terminée.")

    grille_id = fields.Many2one(
        "ev.grille", string="Grille d'évaluation", tracking=True,
        default=lambda self: self.env["ev.grille"].search(
            [("company_id", "in", [False, self.env.company.id])], limit=1),
        help="Grille utilisée pour noter les agents de cette campagne. "
             "Elle se verrouille au lancement : deux agents évalués à trois "
             "semaines d'écart doivent rester comparables.")

    # ------------------------------------------------------------------
    # Ciblage de la population
    # ------------------------------------------------------------------
    population = fields.Selection([
        ("department", "Par direction / département"),
        ("employee", "Liste d'agents"),
        ("company", "Toute la société"),
    ], string="Population", required=True, default="department", tracking=True)
    department_ids = fields.Many2many(
        "hr.department", string="Directions concernées")
    inclure_sous_departements = fields.Boolean(
        string="Inclure les sous-directions", default=True,
        help="Étend le ciblage aux départements rattachés à ceux choisis.")
    employee_ids = fields.Many2many(
        "hr.employee", "ev_campagne_employee_rel", "campagne_id", "employee_id",
        string="Agents concernés")
    employee_exclu_ids = fields.Many2many(
        "hr.employee", "ev_campagne_employee_exclu_rel", "campagne_id",
        "employee_id", string="Agents exclus",
        help="Agents à retirer du ciblage (congé longue durée, départ "
             "programmé, période d'essai...).")

    # ------------------------------------------------------------------
    # Résultat et suivi
    # ------------------------------------------------------------------
    appraisal_ids = fields.One2many(
        "hr.appraisal", "ev_campagne_id", string="Évaluations",
        readonly=True)
    state = fields.Selection([
        ("draft", "Brouillon"),
        ("running", "En cours"),
        ("closed", "Clôturée"),
        ("cancelled", "Annulée"),
    ], string="Statut", default="draft", required=True, copy=False,
        tracking=True)

    nb_cible = fields.Integer(
        string="Agents ciblés", compute="_compute_nb_cible",
        help="Effectif visé par le ciblage actuel, exclusions déduites.")
    nb_genere = fields.Integer(
        string="Évaluations générées", compute="_compute_stats", store=True)
    nb_a_confirmer = fields.Integer(
        string="À confirmer", compute="_compute_stats", store=True)
    nb_confirme = fields.Integer(
        string="Confirmées", compute="_compute_stats", store=True)
    nb_fait = fields.Integer(
        string="Faites", compute="_compute_stats", store=True)
    nb_annule = fields.Integer(
        string="Annulées", compute="_compute_stats", store=True)
    nb_sans_manager = fields.Integer(
        string="Sans évaluateur", compute="_compute_stats", store=True,
        help="Évaluations générées pour un agent dont la fiche ne porte "
             "aucun manager : personne ne pourra les traiter.")
    taux_avancement = fields.Float(
        string="Avancement (%)", compute="_compute_stats", store=True,
        group_operator="avg")

    # --- Objectifs de l'exercice ---
    objectif_ids = fields.One2many(
        "hr.appraisal.goal", "ev_campagne_id", string="Objectifs de la campagne")
    nb_objectifs = fields.Integer(
        string="Objectifs fixés", compute="_compute_stats_objectifs",
        store=True)
    nb_agents_sans_objectif = fields.Integer(
        string="Agents sans objectif", compute="_compute_stats_objectifs",
        store=True,
        help="Agents ayant une évaluation dans cette campagne mais aucun "
             "objectif fixé pour l'exercice.")

    @api.depends("objectif_ids.employee_id", "appraisal_ids.employee_id")
    def _compute_stats_objectifs(self):
        for campagne in self:
            campagne.nb_objectifs = len(campagne.objectif_ids)
            servis = campagne.objectif_ids.employee_id
            concernes = campagne.appraisal_ids.employee_id
            campagne.nb_agents_sans_objectif = len(concernes - servis)

    def action_voir_objectifs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Objectifs — %s", self.name),
            "res_model": "hr.appraisal.goal",
            "view_mode": "tree,form",
            "domain": [("ev_campagne_id", "=", self.id)],
            "context": {"default_ev_campagne_id": self.id,
                        "default_deadline": self.date_fin},
        }

    # ------------------------------------------------------------------
    # Calculs et contraintes
    # ------------------------------------------------------------------
    @api.depends("population", "department_ids", "inclure_sous_departements",
                 "employee_ids", "employee_exclu_ids", "company_id")
    def _compute_nb_cible(self):
        for campagne in self:
            campagne.nb_cible = len(campagne._get_employees_cibles())

    @api.depends("appraisal_ids.state", "appraisal_ids.manager_ids")
    def _compute_stats(self):
        for campagne in self:
            evals = campagne.appraisal_ids
            campagne.nb_genere = len(evals)
            campagne.nb_a_confirmer = len(
                evals.filtered(lambda a: a.state == "new"))
            campagne.nb_confirme = len(
                evals.filtered(lambda a: a.state == "pending"))
            campagne.nb_fait = len(evals.filtered(lambda a: a.state == "done"))
            campagne.nb_annule = len(
                evals.filtered(lambda a: a.state == "cancel"))
            campagne.nb_sans_manager = len(
                evals.filtered(lambda a: not a.manager_ids))
            # L'avancement se mesure sur les évaluations réellement à traiter :
            # une évaluation annulée ne compte ni au numérateur ni au diviseur.
            a_traiter = campagne.nb_genere - campagne.nb_annule
            campagne.taux_avancement = (
                100.0 * campagne.nb_fait / a_traiter) if a_traiter else 0.0

    @api.constrains("date_debut", "date_fin", "date_evaluation")
    def _check_dates(self):
        """Cohérence des trois dates : l'entretien se tient forcément entre
        l'ouverture et l'échéance de la campagne."""
        for campagne in self:
            if campagne.date_fin < campagne.date_debut:
                raise ValidationError(_(
                    "L'échéance de la campagne (%(fin)s) ne peut pas "
                    "précéder son ouverture (%(debut)s).",
                    fin=campagne.date_fin.strftime("%d/%m/%Y"),
                    debut=campagne.date_debut.strftime("%d/%m/%Y")))
            if campagne.date_evaluation < campagne.date_debut:
                raise ValidationError(_(
                    "La date d'entretien prévue (%(eval)s) précède "
                    "l'ouverture de la campagne (%(debut)s) : les entretiens "
                    "ne peuvent pas commencer avant que l'exercice soit "
                    "ouvert.",
                    eval=campagne.date_evaluation.strftime("%d/%m/%Y"),
                    debut=campagne.date_debut.strftime("%d/%m/%Y")))
            if campagne.date_evaluation > campagne.date_fin:
                raise ValidationError(_(
                    "La date d'entretien prévue (%(eval)s) dépasse "
                    "l'échéance de la campagne (%(fin)s) : les entretiens "
                    "seraient programmés après la clôture de l'exercice.",
                    eval=campagne.date_evaluation.strftime("%d/%m/%Y"),
                    fin=campagne.date_fin.strftime("%d/%m/%Y")))

    # ------------------------------------------------------------------
    # Ciblage
    # ------------------------------------------------------------------
    def _get_employees_cibles(self):
        """Les agents visés par le ciblage courant, exclusions déduites.

        Toujours restreint à la société de la campagne et aux employés
        actifs : une campagne ne concerne jamais un agent parti.
        """
        self.ensure_one()
        Employee = self.env["hr.employee"]
        if not self.company_id:
            return Employee
        domain = [("company_id", "=", self.company_id.id)]

        if self.population == "department":
            departments = self.department_ids
            if not departments:
                return Employee
            if self.inclure_sous_departements:
                departments = self.env["hr.department"].search(
                    [("id", "child_of", departments.ids)])
            domain.append(("department_id", "in", departments.ids))
        elif self.population == "employee":
            if not self.employee_ids:
                return Employee
            domain.append(("id", "in", self.employee_ids.ids))
        # population == "company" : aucun filtre supplémentaire

        return Employee.search(domain) - self.employee_exclu_ids

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def action_lancer(self):
        """Brouillon -> En cours : génère une évaluation par agent ciblé.

        Idempotent : un agent qui a déjà une évaluation dans cette campagne
        n'en reçoit pas une seconde. On peut donc relancer après avoir
        élargi le ciblage.
        """
        for campagne in self:
            if campagne.state not in ("draft", "running"):
                raise UserError(_(
                    "Seule une campagne en brouillon ou en cours peut "
                    "générer des évaluations."))
            employees = campagne._get_employees_cibles()
            if not employees:
                # Le ciblage est TOUJOURS borné à la société de la campagne.
                # C'est la cause la plus fréquente d'un ciblage vide, et
                # celle qu'on ne devine pas : on la nomme.
                raise UserError(_(
                    "Aucun agent ne correspond au ciblage de « %(camp)s ».\n\n"
                    "Le ciblage ne retient que les agents **actifs** de la "
                    "société « %(societe)s ». Vérifiez dans cet ordre :\n"
                    "• la société de la campagne — c'est la cause la plus "
                    "fréquente, les agents visés peuvent appartenir à une "
                    "autre société ;\n"
                    "• la population choisie et son contenu ;\n"
                    "• la liste des agents exclus.",
                    camp=campagne.name or "",
                    societe=campagne.company_id.name or _("non renseignée")))

            campagne._check_date_entretien_au_lancement()
            campagne._check_pas_deja_dans_une_autre_campagne(employees)

            deja_traites = campagne.appraisal_ids.employee_id
            a_creer = employees - deja_traites
            if not a_creer:
                raise UserError(_(
                    "Tous les agents ciblés ont déjà leur évaluation dans "
                    "cette campagne (%s au total).", len(deja_traites)))

            campagne._creer_evaluations(a_creer)
            campagne.state = "running"

    def _check_date_entretien_au_lancement(self):
        """Au LANCEMENT seulement : on ne programme pas des entretiens dans
        le passé. Un brouillon, lui, peut garder une date dépassée le temps
        d'être corrigé (même principe que les ordres de mission)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        if self.date_evaluation < today:
            raise UserError(_(
                "La date d'entretien prévue (%(date)s) est déjà passée : on "
                "ne peut pas programmer des entretiens dans le passé. "
                "Corrigez la date avant de lancer la campagne.",
                date=self.date_evaluation.strftime("%d/%m/%Y")))

    def _check_pas_deja_dans_une_autre_campagne(self, employees):
        """Un agent ne peut pas être évalué deux fois sur le même exercice :
        deux campagnes concurrentes produiraient deux notations pour la même
        année, sans qu'on sache laquelle fait foi."""
        self.ensure_one()
        autres = self.search([
            ("id", "!=", self.id),
            ("exercice", "=", self.exercice),
            ("company_id", "=", self.company_id.id),
            ("state", "in", ("running", "closed")),
        ])
        if not autres:
            return
        conflits = autres.appraisal_ids.filtered(
            lambda a: a.employee_id in employees and a.state != "cancel")
        if conflits:
            detail = ", ".join(
                "%s (%s)" % (a.employee_id.name, a.ev_campagne_id.name)
                for a in conflits[:10])
            raise UserError(_(
                "%(nb)s agent(s) figurent déjà dans une autre campagne de "
                "l'exercice %(ex)s : %(detail)s%(suite)s\n\n"
                "Excluez-les du ciblage, ou annulez leur évaluation dans "
                "l'autre campagne.",
                nb=len(conflits), ex=self.exercice, detail=detail,
                suite="..." if len(conflits) > 10 else ""))

    def _creer_evaluations(self, employees):
        """Crée les évaluations standard pour les agents donnés."""
        self.ensure_one()
        vals_list = []
        for employee in employees:
            vals_list.append({
                "employee_id": employee.id,
                # L'évaluateur est le supérieur de la fiche employé. Vide,
                # l'évaluation reste créée mais est signalée au tableau de
                # bord (nb_sans_manager) : aux RH de compléter la hiérarchie.
                "manager_ids": [(6, 0, employee.parent_id.ids)],
                "date_close": self.date_evaluation,
                "ev_campagne_id": self.id,
                # Confidentialité : chacun rédige à l'abri du regard de
                # l'autre et publie quand il est prêt. Le standard coche ces
                # deux cases par défaut, ce qui expose les brouillons.
                "employee_feedback_published": False,
                "manager_feedback_published": False,
            })
        evaluations = self.env["hr.appraisal"].create(vals_list)

        # Photographie du circuit : les phases sont figées maintenant, avec
        # leur acteur résolu. Une phase configurée après coup n'entrera pas
        # dans les évaluations déjà lancées.
        phases = self.env["ev.circuit.phase"].search(
            [("company_id", "in", [False, self.company_id.id])])
        if phases:
            evaluations._ev_creer_photo(phases=phases)

        # Notation : la grille est posée maintenant, avec une ligne par
        # critère. Elle se verrouille du fait même de ce lancement.
        if self.grille_id:
            evaluations._ev_creer_notation(self.grille_id)

        sans_manager = evaluations.filtered(lambda a: not a.manager_ids)
        message = _(
            "%(nb)s évaluation(s) générée(s) pour la campagne, à la date du "
            "%(date)s.", nb=len(evaluations),
            date=self.date_evaluation.strftime("%d/%m/%Y"))
        if sans_manager:
            message += _(
                "<br/><b>%(nb)s agent(s) sans évaluateur</b> : %(noms)s. "
                "Renseignez leur manager sur la fiche employé, puis "
                "complétez l'évaluation.",
                nb=len(sans_manager),
                noms=", ".join(sans_manager.employee_id.mapped("name")))
        self.message_post(body=message)
        return evaluations

    def action_cloturer(self):
        """En cours -> Clôturée. Les évaluations restent consultables."""
        for campagne in self:
            if campagne.state != "running":
                raise UserError(_(
                    "Seule une campagne en cours peut être clôturée."))
            restantes = campagne.appraisal_ids.filtered(
                lambda a: a.state in ("new", "pending"))
            campagne.state = "closed"
            if restantes:
                campagne.message_post(body=_(
                    "Campagne clôturée avec %(nb)s évaluation(s) encore "
                    "ouverte(s) : %(noms)s.", nb=len(restantes),
                    noms=", ".join(restantes.employee_id.mapped("name")[:15])))
            else:
                campagne.message_post(body=_(
                    "Campagne clôturée — les %s évaluations sont traitées.",
                    campagne.nb_genere))

    def action_annuler(self):
        """Annule la campagne. Les évaluations déjà générées ne sont PAS
        supprimées : elles gardent leur valeur de dossier. Aux RH de les
        annuler une à une si l'exercice est abandonné."""
        for campagne in self:
            if campagne.state == "closed":
                raise UserError(_(
                    "Une campagne clôturée ne peut plus être annulée."))
            campagne.state = "cancelled"
            campagne.message_post(body=_(
                "Campagne annulée. Les %s évaluation(s) déjà générée(s) "
                "restent en place.", campagne.nb_genere))

    def action_remettre_brouillon(self):
        for campagne in self:
            if campagne.state != "cancelled":
                raise UserError(_(
                    "Seule une campagne annulée peut revenir en brouillon."))
            campagne.state = "draft"

    # ------------------------------------------------------------------
    # Boutons de consultation
    # ------------------------------------------------------------------
    def action_voir_population(self):
        self.ensure_one()
        employees = self._get_employees_cibles()
        return {
            "type": "ir.actions.act_window",
            "name": _("Agents ciblés — %s", self.name),
            "res_model": "hr.employee",
            "view_mode": "tree,form",
            "domain": [("id", "in", employees.ids)],
            "context": {"create": False},
        }

    def action_ev_export_xlsx(self):
        """Télécharge le récapitulatif de la campagne, au format Excel."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": "/gestion_evaluation/campagne/%s.xlsx" % self.id,
        }

    def action_voir_evaluations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Évaluations — %s", self.name),
            "res_model": "hr.appraisal",
            "view_mode": "tree,form",
            "domain": [("ev_campagne_id", "=", self.id)],
            "context": {"create": False},
        }

    # ------------------------------------------------------------------
    # Garde-fou
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Suppression
    # ------------------------------------------------------------------
    def _evaluations_engagees(self):
        """Évaluations qui ont dépassé le stade « À confirmer ».

        Une évaluation confirmée, faite ou en cours de circuit porte du
        travail réel : elle ne doit jamais disparaître avec sa campagne.
        """
        self.ensure_one()
        return self.appraisal_ids.filtered(
            lambda a: a.state not in ("new", "cancel"))

    def action_supprimer_evaluations(self):
        """Efface les évaluations générées, quand aucune n'a été engagée.

        Sert à défaire une campagne lancée par erreur ou montée pour un
        essai : sans cela, il faudrait les supprimer une à une avant de
        pouvoir supprimer la campagne.
        """
        for campagne in self:
            engagees = campagne._evaluations_engagees()
            if engagees:
                raise UserError(_(
                    "%(nb)s évaluation(s) de cette campagne ont déjà été "
                    "engagées (%(detail)s) : elles portent du travail réel "
                    "et ne peuvent pas être effacées en bloc.\n\nPour les "
                    "retirer malgré tout, annulez-les une à une depuis la "
                    "liste des évaluations.",
                    nb=len(engagees),
                    detail=", ".join(
                        "%s — %s" % (a.employee_id.name,
                                     dict(a._fields["state"].selection).get(
                                         a.state, a.state))
                        for a in engagees[:8])))
            nb = len(campagne.appraisal_ids)
            if not nb:
                raise UserError(_(
                    "Cette campagne n'a généré aucune évaluation."))
            campagne.appraisal_ids.unlink()
            campagne.message_post(body=_(
                "%s évaluation(s) générée(s) supprimée(s) par %s. La "
                "campagne peut désormais être supprimée.",
                nb, self.env.user.name))

    def unlink(self):
        """Une campagne qui a généré des évaluations ne se supprime pas
        d'un trait : elle est la trace de l'exercice."""
        for campagne in self:
            if campagne.appraisal_ids:
                engagees = campagne._evaluations_engagees()
                if engagees:
                    raise UserError(_(
                        "La campagne « %(nom)s » porte %(nb)s évaluation(s), "
                        "dont %(eng)s déjà engagée(s) : elle ne peut pas être "
                        "supprimée. Une campagne dont le travail a commencé "
                        "reste la trace de l'exercice — annulez-la plutôt.",
                        nom=campagne.name, nb=len(campagne.appraisal_ids),
                        eng=len(engagees)))
                raise UserError(_(
                    "La campagne « %(nom)s » a généré %(nb)s évaluation(s). "
                    "Aucune n'a été engagée : utilisez le bouton "
                    "« Supprimer les évaluations générées » sur la campagne, "
                    "puis supprimez-la.",
                    nom=campagne.name, nb=len(campagne.appraisal_ids)))
        return super().unlink()
