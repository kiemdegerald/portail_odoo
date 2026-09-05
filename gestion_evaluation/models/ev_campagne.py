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

    # --- Le temps de l'ÉVALUATION -----------------------------------
    # Les objectifs, eux, ont leur propre période, bien plus tôt dans
    # l'exercice — voir le modèle `ev.periode.objectifs`.
    date_debut = fields.Date(
        string="Ouverture de l'évaluation", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self),
        help="Jour où l'évaluation s'ouvre : à partir de là, chacun "
             "remplit sa grille. Les objectifs, eux, ont été fixés en "
             "début d'exercice — leur période se termine avant cette "
             "date. Repère de planification : rien n'en est reporté sur "
             "les évaluations.")
    date_fin = fields.Date(
        string="Échéance de l'évaluation", required=True, tracking=True,
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
        domain="[('campagne_photo_id', '=', False)]",
        default=lambda self: self.env["ev.grille"].search(
            [("company_id", "in", [False, self.env.company.id]),
             ("campagne_photo_id", "=", False)], limit=1),
        help="Grille de référence choisie pour cette campagne. Au "
             "lancement, la campagne en emporte une COPIE FIGÉE : deux "
             "agents évalués à trois semaines d'écart doivent rester "
             "comparables, et retoucher la grille ensuite ne doit affecter "
             "que les campagnes suivantes.")
    grille_photo_id = fields.Many2one(
        "ev.grille", string="Grille figée de la campagne",
        readonly=True, copy=False,
        help="Copie de la grille prise au lancement. C'est elle que "
             "portent les évaluations : elle ne bouge plus.")
    echelle_photo_ids = fields.One2many(
        "ev.echelle.niveau", "campagne_photo_id",
        string="Échelle figée de la campagne", readonly=True,
        help="Copie de l'échelle de notation prise au lancement : les "
             "libellés lus sur les évaluations de cette campagne ne "
             "changeront plus.")

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
    # La campagne ne s'occupe QUE de l'évaluation. La fixation des
    # objectifs est un objet à part — `ev.periode.objectifs` — ouvert en
    # début d'exercice, des mois avant que la campagne n'existe. Les deux
    # se rejoignent par l'EXERCICE.
    state = fields.Selection([
        ("draft", "Brouillon"),
        ("running", "Évaluation en cours"),
        ("closed", "Clôturée"),
        ("cancelled", "Annulée"),
    ], string="Statut", default="draft", required=True, copy=False,
        tracking=True)

    # --- La fenêtre de fixation des objectifs ---------------------------
    # Elle n'appartient plus à la campagne : c'est la PÉRIODE du même
    # exercice qui l'ouvre et la ferme. La campagne se contente de la
    # relayer, pour que les écrans et les contrôles existants continuent
    # d'obtenir une réponse.
    periode_objectifs_id = fields.Many2one(
        "ev.periode.objectifs", string="Période d'objectifs",
        compute="_compute_periode_objectifs",
        help="Période de fixation des objectifs du même exercice et de la "
             "même société.")
    objectifs_ouverts = fields.Boolean(
        string="Objectifs ouverts", compute="_compute_objectifs_ouverts",
        help="Vrai si la période de fixation des objectifs de l'exercice "
             "est ouverte.")

    @api.depends("exercice", "company_id")
    def _compute_periode_objectifs(self):
        Periode = self.env["ev.periode.objectifs"].sudo()
        for campagne in self:
            campagne.periode_objectifs_id = Periode._periode_de_lexercice(
                campagne.exercice, campagne.company_id)

    @api.depends("periode_objectifs_id.ouverte")
    def _compute_objectifs_ouverts(self):
        for campagne in self:
            campagne.objectifs_ouverts = bool(
                campagne.periode_objectifs_id.ouverte)

    def _ev_motif_objectifs_fermes(self):
        """None si les objectifs se saisissent, sinon le motif du refus.

        La réponse vient de la PÉRIODE de l'exercice. Si aucune période
        n'a jamais été ouverte, on le dit : c'est la seule chose à faire
        pour débloquer la situation.
        """
        self.ensure_one()
        periode = self.periode_objectifs_id
        if not periode:
            return _(
                "Aucune période de fixation des objectifs n'a été ouverte "
                "pour l'exercice %s. Le service RH doit l'ouvrir "
                "(Évaluations > Fixation des objectifs).", self.exercice or "")
        return periode._ev_motif_ferme()

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
        string="Objectifs fixés", compute="_compute_stats_objectifs")
    nb_agents_sans_objectif = fields.Integer(
        string="Agents sans objectif", compute="_compute_stats_objectifs",
        help="Agents ayant une évaluation dans cette campagne mais aucun "
             "objectif fixé pour l'exercice. Compté À LA VOLÉE : les "
             "objectifs vivent dans la période de l'exercice, pas dans la "
             "campagne — stocké, ce compteur resterait périmé.")

    @api.depends("objectif_ids.employee_id", "appraisal_ids.employee_id",
                 "exercice")
    def _compute_stats_objectifs(self):
        """Les objectifs comptés sont ceux de l'EXERCICE, pas ceux de la
        campagne : ils ont été fixés en janvier, au titre d'une période,
        bien avant que cette campagne n'existe."""
        Goal = self.env["hr.appraisal.goal"].sudo()
        for campagne in self:
            concernes = campagne.appraisal_ids.filtered(
                lambda a: a.state != "cancel").employee_id
            objectifs = Goal.search([
                ("employee_id", "in", concernes.ids),
                ("ev_exercice", "=", campagne.exercice),
            ]) if concernes else Goal
            campagne.nb_objectifs = len(objectifs)
            campagne.nb_agents_sans_objectif = len(
                concernes - objectifs.employee_id)

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
                    "L'échéance de l'évaluation (%(fin)s) ne peut pas "
                    "précéder son ouverture (%(debut)s).",
                    fin=campagne.date_fin.strftime("%d/%m/%Y"),
                    debut=campagne.date_debut.strftime("%d/%m/%Y")))
            if campagne.date_evaluation < campagne.date_debut:
                raise ValidationError(_(
                    "La date d'entretien prévue (%(eval)s) précède "
                    "l'ouverture de l'évaluation (%(debut)s) : les entretiens "
                    "ne peuvent pas se tenir avant que l'évaluation soit "
                    "ouverte.",
                    eval=campagne.date_evaluation.strftime("%d/%m/%Y"),
                    debut=campagne.date_debut.strftime("%d/%m/%Y")))
            if campagne.date_evaluation > campagne.date_fin:
                raise ValidationError(_(
                    "La date d'entretien prévue (%(eval)s) dépasse "
                    "l'échéance de l'évaluation (%(fin)s) : les entretiens "
                    "seraient programmés après la clôture de l'exercice.",
                    eval=campagne.date_evaluation.strftime("%d/%m/%Y"),
                    fin=campagne.date_fin.strftime("%d/%m/%Y")))

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
                    "Seule une campagne en brouillon ou en cours "
                    "d'évaluation peut générer des évaluations."))
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

            campagne._ev_photographier_grille()
            campagne._ev_photographier_echelle()
            campagne._creer_evaluations(a_creer)
            if campagne.state == "draft":
                campagne.state = "running"
            for appraisal in campagne.appraisal_ids:
                appraisal._ev_demarrer_evaluation()
            # Les objectifs ont été fixés en début d'exercice, dans leur
            # propre période. On ne bloque pas si certains manquent —
            # bloquer punirait l'agent, pas le responsable en retard — mais
            # on le DIT, et on rappelle le recours : rouvrir la période.
            sans = campagne._agents_sans_objectif()
            if sans:
                campagne.message_post(body=_(
                    "Évaluation ouverte. ATTENTION : %(nb)s agent(s) "
                    "abordent l'exercice SANS AUCUN OBJECTIF fixé "
                    "(%(qui)s). Rouvrez la période de fixation des "
                    "objectifs (Évaluations > Fixation des objectifs) pour "
                    "que leur responsable les renseigne.",
                    nb=len(sans), qui=", ".join(sans.mapped("name")[:10])))
            else:
                campagne.message_post(body=_(
                    "Évaluation ouverte. Tous les agents ont des objectifs "
                    "pour l'exercice %s.", campagne.exercice or ""))

    def _agents_sans_objectif(self):
        """Les agents de la campagne sans aucun objectif POUR L'EXERCICE.

        On ne regarde plus les objectifs rattachés à la campagne : ils
        sont fixés en début d'année au titre d'une période, la campagne
        n'existait pas encore.
        """
        self.ensure_one()
        concernes = self.appraisal_ids.filtered(
            lambda a: a.state != "cancel").employee_id
        if not concernes:
            return self.env["hr.employee"]
        servis = self.env["hr.appraisal.goal"].sudo().search([
            ("employee_id", "in", concernes.ids),
            ("ev_exercice", "=", self.exercice),
        ]).employee_id
        return concernes - servis

    def action_voir_grille_figee(self):
        """La grille sur laquelle cette campagne a réellement noté.

        On y accède depuis la campagne, jamais depuis une liste de
        copies : ce qu'on cherche à savoir, c'est « sur quoi cet agent
        a-t-il été noté cette année-là », et la question part toujours de
        la campagne.
        """
        self.ensure_one()
        if not self.grille_photo_id:
            raise UserError(_(
                "La campagne « %s » n'a pas encore été lancée : elle "
                "n'a donc pas encore figé sa grille.", self.name or ""))
        return {
            "type": "ir.actions.act_window",
            "name": _("Grille figée — %s", self.name),
            "res_model": "ev.grille",
            "res_id": self.grille_photo_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def _ev_photographier_grille(self):
        """La campagne emporte sa propre copie de la grille, figée.

        Sans cela, retoucher la grille de référence modifiait les
        évaluations DÉJÀ EN COURS : un critère déplacé d'un thème à
        l'autre changeait les moyennes sous les yeux des évaluateurs.

        La photo se prend une seule fois, au premier lancement. Relancer
        la campagne pour y ajouter des agents réutilise la MÊME photo :
        tous les agents d'une campagne sont notés sur la même grille,
        c'est la condition pour que leurs notes se comparent.
        """
        self.ensure_one()
        if self.grille_photo_id or not self.grille_id:
            return self.grille_photo_id
        photo, _corr = self.grille_id._ev_photographier(self)
        self.sudo().grille_photo_id = photo
        return photo

    def _ev_photographier_echelle(self):
        """La campagne emporte aussi sa copie de l'échelle de notation.

        La VALEUR d'un niveau était déjà recopiée sur la note à la saisie
        — modifier l'échelle ne réécrivait donc aucune note. Mais le
        LIBELLÉ était lu vif : renommer « Excellence » changeait le mot
        lu sur les évaluations passées. Une campagne lancée garde donc
        les libellés qu'elle a photographiés.
        """
        self.ensure_one()
        if self.echelle_photo_ids:
            return self.echelle_photo_ids
        copies, _corr = self.env["ev.echelle.niveau"]._ev_photographier(self)
        return copies

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
        # On note sur la PHOTO, jamais sur la grille de référence.
        grille = self.grille_photo_id or self.grille_id
        if grille:
            evaluations._ev_creer_notation(grille)

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
