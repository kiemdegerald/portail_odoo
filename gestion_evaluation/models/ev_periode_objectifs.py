# -*- coding: utf-8 -*-
"""Période de fixation des objectifs.

Les objectifs se fixent en DÉBUT d'exercice ; l'évaluation se fait en fin
d'exercice, des mois plus tard. Confondre les deux — comme le faisait la
campagne, qui ouvrait les objectifs en même temps qu'elle générait les
évaluations — revenait à inventer les objectifs le jour où on note.

Les deux objets sont donc séparés, et reliés par l'EXERCICE : la campagne
« Évaluation 2027 » lit les objectifs de la période « Objectifs 2027 ».
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EvPeriodeObjectifs(models.Model):
    _name = "ev.periode.objectifs"
    _description = "Période de fixation des objectifs"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_debut desc, id desc"

    name = fields.Char(
        string="Intitulé", required=True, tracking=True,
        help="Ex. : Objectifs 2027.")
    exercice = fields.Char(
        string="Exercice", required=True, tracking=True, index=True,
        default=lambda self: str(fields.Date.context_today(self).year),
        help="Année de référence. C'est ce champ qui relie la période à la "
             "campagne d'évaluation du même exercice.")
    company_id = fields.Many2one(
        "res.company", string="Société", required=True,
        default=lambda self: self.env.company)

    date_debut = fields.Date(
        string="Ouverture de la période", required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self),
        help="Premier jour où les responsables peuvent fixer les objectifs "
             "de leurs collaborateurs.")
    date_fin = fields.Date(
        string="Clôture de la période", required=True, tracking=True,
        help="Dernier jour de la période. Passée cette date, les objectifs "
             "ne se saisissent plus — sauf réouverture par le service RH.")

    state = fields.Selection([
        ("draft", "Brouillon"),
        ("open", "Ouverte"),
        ("closed", "Fermée"),
        ("cancelled", "Annulée"),
    ], string="Statut", default="draft", required=True, copy=False,
        tracking=True)

    # ------------------------------------------------------------------
    # Ciblage de la population — même logique que la campagne
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
        "hr.employee", "ev_periode_employee_rel", "periode_id", "employee_id",
        string="Agents concernés")
    employee_exclu_ids = fields.Many2many(
        "hr.employee", "ev_periode_employee_exclu_rel", "periode_id",
        "employee_id", string="Agents exclus",
        help="Agents à retirer du ciblage (congé longue durée, départ "
             "programmé, période d'essai...).")

    # ------------------------------------------------------------------
    # Suivi
    # ------------------------------------------------------------------
    goal_ids = fields.One2many(
        "hr.appraisal.goal", "ev_periode_id", string="Objectifs fixés",
        readonly=True)
    nb_agents = fields.Integer(
        string="Agents visés", compute="_compute_avancement")
    nb_avec_objectif = fields.Integer(
        string="Agents servis", compute="_compute_avancement")
    nb_sans_objectif = fields.Integer(
        string="Agents sans objectif", compute="_compute_avancement")
    ouverte = fields.Boolean(
        string="Saisie ouverte", compute="_compute_ouverte",
        help="La période accepte-t-elle des objectifs aujourd'hui ?")

    @api.depends("state", "date_debut", "date_fin")
    def _compute_ouverte(self):
        aujourdhui = fields.Date.context_today(self)
        for periode in self:
            periode.ouverte = bool(
                periode.state == "open"
                and (not periode.date_debut or periode.date_debut <= aujourdhui)
                and (not periode.date_fin or aujourdhui <= periode.date_fin))

    @api.depends("goal_ids.employee_id", "population", "department_ids",
                 "employee_ids", "employee_exclu_ids",
                 "inclure_sous_departements", "company_id")
    def _compute_avancement(self):
        for periode in self:
            cibles = periode._get_employees_cibles()
            servis = periode.goal_ids.employee_id & cibles
            periode.nb_agents = len(cibles)
            periode.nb_avec_objectif = len(servis)
            periode.nb_sans_objectif = len(cibles) - len(servis)

    # ------------------------------------------------------------------
    # Ciblage
    # ------------------------------------------------------------------
    def _get_employees_cibles(self):
        """Les agents visés, exclusions déduites. Toujours borné à la
        société de la période et aux employés actifs."""
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
    # Contrôles
    # ------------------------------------------------------------------
    @api.constrains("date_debut", "date_fin")
    def _check_dates(self):
        for periode in self:
            if (periode.date_debut and periode.date_fin
                    and periode.date_fin < periode.date_debut):
                raise ValidationError(_(
                    "La clôture de la période ne peut pas précéder son "
                    "ouverture."))

    @api.constrains("exercice", "company_id", "state")
    def _check_exercice_unique(self):
        """Un seul exercice ouvert à la fois par société : deux périodes
        concurrentes rendraient impossible de dire à quel exercice se
        rattache un objectif saisi aujourd'hui."""
        for periode in self:
            if periode.state in ("draft", "cancelled"):
                continue
            if self.search_count([
                ("id", "!=", periode.id),
                ("exercice", "=", periode.exercice),
                ("company_id", "=", periode.company_id.id),
                ("state", "in", ("open", "closed")),
            ]):
                raise ValidationError(_(
                    "Une période d'objectifs existe déjà pour l'exercice "
                    "%(ex)s dans la société « %(soc)s ». Rouvrez-la plutôt "
                    "que d'en créer une seconde : les objectifs d'un même "
                    "exercice doivent tous se retrouver au même endroit.",
                    ex=periode.exercice, soc=periode.company_id.name))

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def action_ouvrir(self):
        """Brouillon -> Ouverte : les responsables peuvent saisir."""
        for periode in self:
            if periode.state not in ("draft", "closed"):
                raise UserError(_(
                    "Seule une période en brouillon ou fermée peut être "
                    "ouverte."))
            if not periode._get_employees_cibles():
                raise UserError(_(
                    "Aucun agent ne correspond au ciblage de « %(nom)s ».\n\n"
                    "Le ciblage ne retient que les agents **actifs** de la "
                    "société « %(soc)s ». Vérifiez la société, la population "
                    "choisie et la liste des agents exclus.",
                    nom=periode.name or "", soc=periode.company_id.name
                    or _("non renseignée")))
            ancien = periode.state
            periode.state = "open"
            periode.message_post(body=_(
                "Période ouverte : %(nb)s agent(s) visé(s), du %(du)s au "
                "%(au)s.%(reouverture)s",
                nb=len(periode._get_employees_cibles()),
                du=periode.date_debut.strftime("%d/%m/%Y")
                if periode.date_debut else "—",
                au=periode.date_fin.strftime("%d/%m/%Y")
                if periode.date_fin else "—",
                reouverture=_(" (réouverture)") if ancien == "closed" else ""))

    def action_fermer(self):
        """Ouverte -> Fermée. Les objectifs restent lisibles, plus
        modifiables. La RH peut rouvrir à tout moment."""
        for periode in self:
            if periode.state != "open":
                raise UserError(_("Seule une période ouverte peut être "
                                  "fermée."))
            periode.state = "closed"
            manquants = periode._agents_sans_objectif()
            periode.message_post(body=_(
                "Période fermée. %(servis)s agent(s) servi(s) sur "
                "%(total)s.%(manque)s",
                servis=periode.nb_avec_objectif, total=periode.nb_agents,
                manque=(_(" Sans objectif : %s.")
                        % ", ".join(manquants.mapped("name")[:12])
                        if manquants else "")))

    def action_annuler(self):
        for periode in self:
            if periode.state == "cancelled":
                raise UserError(_("Cette période est déjà annulée."))
            periode.state = "cancelled"

    def action_remettre_brouillon(self):
        for periode in self:
            if periode.goal_ids:
                raise UserError(_(
                    "%s objectif(s) ont déjà été fixés au titre de cette "
                    "période : elle ne peut plus revenir en brouillon. "
                    "Fermez-la, ou annulez-la.", len(periode.goal_ids)))
            periode.state = "draft"

    # ------------------------------------------------------------------
    # Aides
    # ------------------------------------------------------------------
    def _agents_sans_objectif(self):
        """Les agents visés qui n'ont reçu aucun objectif."""
        self.ensure_one()
        return self._get_employees_cibles() - self.goal_ids.employee_id

    def action_voir_objectifs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Objectifs — %s", self.name),
            "res_model": "hr.appraisal.goal",
            "view_mode": "tree,form",
            "domain": [("ev_periode_id", "=", self.id)],
            "context": {"default_ev_periode_id": self.id,
                        "default_ev_campagne_id": False},
        }

    def action_fixer_objectif(self):
        """Le service RH saisit à la place d'un responsable absent."""
        self.ensure_one()
        self._ev_check_ouverte()
        return {
            "type": "ir.actions.act_window",
            "name": _("Fixer un objectif"),
            "res_model": "ev.objectif.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_periode_id": self.id},
        }

    def action_voir_sans_objectif(self):
        """Les agents oubliés : c'est la liste que la RH relance."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sans objectif — %s", self.name),
            "res_model": "hr.employee",
            "view_mode": "tree,form",
            "domain": [("id", "in", self._agents_sans_objectif().ids)],
        }

    # ------------------------------------------------------------------
    # Saisie des objectifs — sans aucune évaluation
    # ------------------------------------------------------------------
    def _ev_motif_ferme(self):
        """Pourquoi la saisie est fermée, en une phrase lisible.

        Un écran qui grise un bouton sans dire pourquoi laisse
        l'utilisateur sans recours : il faut qu'il sache s'il doit
        attendre, ou demander une réouverture au service RH.
        """
        self.ensure_one()
        if self.ouverte:
            return None
        aujourdhui = fields.Date.context_today(self)
        if self.state == "draft":
            return _("La période n'est pas encore ouverte par le service "
                     "RH.")
        if self.state == "cancelled":
            return _("Cette période a été annulée.")
        if self.state == "closed":
            return _("La période de fixation des objectifs est fermée. "
                     "Demandez au service RH de la rouvrir si un objectif "
                     "reste à saisir.")
        if self.date_debut and aujourdhui < self.date_debut:
            return _("La saisie des objectifs s'ouvre le %s.",
                     self.date_debut.strftime("%d/%m/%Y"))
        if self.date_fin and aujourdhui > self.date_fin:
            return _("La saisie des objectifs s'est terminée le %s. "
                     "Demandez au service RH de rouvrir la période.",
                     self.date_fin.strftime("%d/%m/%Y"))
        return _("La saisie des objectifs est fermée.")

    def _ev_check_ouverte(self):
        motif = self._ev_motif_ferme()
        if motif:
            raise UserError(motif)

    def _ev_agents_du_responsable(self, responsable):
        """Les collaborateurs DIRECTS du responsable, dans le ciblage.

        On ne descend pas toute la hiérarchie : un objectif se fixe entre
        un agent et son supérieur immédiat, c'est lui qui répond de la
        commande passée.
        """
        self.ensure_one()
        if not responsable:
            return self.env["hr.employee"]
        return self._get_employees_cibles().filtered(
            lambda e: e.parent_id == responsable)

    def _ev_objectifs_de(self, employee):
        """Les objectifs de CET agent au titre de CETTE période."""
        self.ensure_one()
        return self.goal_ids.filtered(lambda g: g.employee_id == employee)

    def _ev_objectif_creer(self, employee, libelle, echeance=None,
                           description=None, manager=None):
        """Fixe un objectif à un agent, au titre de cette période.

        `manager` : le responsable qui passe la commande. Renseigné quand
        le service RH saisit à la place d'un responsable absent — sinon
        c'est le supérieur hiérarchique de l'agent.
        """
        self.ensure_one()
        self._ev_check_ouverte()
        if employee not in self._get_employees_cibles():
            raise UserError(_(
                "%s n'est pas dans la population visée par cette période.",
                employee.name or ""))
        libelle = (libelle or "").strip()
        if not libelle:
            raise UserError(_("Un objectif doit avoir un intitulé."))
        # Un objectif s'énonce en une phrase. Sans borne, un copier-coller
        # malheureux déforme durablement le tableau de l'agent.
        if len(libelle) > 200:
            raise UserError(_(
                "L'intitulé de l'objectif est trop long (%(n)s caractères "
                "pour %(max)s au maximum). Résumez-le en une phrase et "
                "mettez le détail dans les précisions.",
                n=len(libelle), max=200))
        # Deux objectifs identiques n'ont pas de sens, et un double clic
        # sur « Ajouter » suffisait à en créer trois.
        if any((g.name or "").strip().lower() == libelle.lower()
               for g in self._ev_objectifs_de(employee)):
            raise UserError(_(
                "« %s » figure déjà parmi les objectifs de %s pour cet "
                "exercice.", libelle, employee.name or ""))
        if echeance:
            try:
                echeance = fields.Date.to_date(echeance)
            except (ValueError, TypeError):
                raise UserError(_(
                    "L'échéance « %s » n'est pas une date valide.", echeance))
        # `manager_id` est OBLIGATOIRE sur l'objectif standard d'Odoo, et
        # son calcul par défaut s'appuie sur `env.user.employee_id` — vide
        # pour un utilisateur portail. On le renseigne donc explicitement.
        responsable = manager or employee.parent_id
        if not responsable:
            raise UserError(_(
                "Aucun responsable n'est identifié pour %s : impossible de "
                "lui fixer un objectif. Le service RH doit d'abord "
                "renseigner son supérieur hiérarchique.", employee.name or ""))
        return self.env["hr.appraisal.goal"].sudo().create({
            "name": libelle,
            "employee_id": employee.id,
            "manager_id": responsable.id,
            "ev_periode_id": self.id,
            "deadline": echeance or False,
            "description": description or False,
        })

    def _ev_activite_creer(self, objectif_id, libelle, resultat_attendu=None):
        """Ajoute une activité sous un objectif de CETTE période.

        L'identifiant vient d'un formulaire web : on ne retient que les
        objectifs de la période, un identifiant étranger n'atteint rien.
        """
        self.ensure_one()
        self._ev_check_ouverte()
        objectif = self._objectif_de_la_periode(objectif_id)
        libelle = (libelle or "").strip()
        if not libelle:
            raise UserError(_("Une activité doit avoir un libellé."))
        return self.env["ev.objectif.activite"].sudo().create({
            "goal_id": objectif.id,
            "name": libelle,
            "resultat_attendu": (resultat_attendu or "").strip() or False,
        })

    def _ev_activite_supprimer(self, activite_id):
        self.ensure_one()
        self._ev_check_ouverte()
        try:
            activite_id = int(activite_id or 0)
        except (TypeError, ValueError):
            activite_id = 0
        activite = self.env["ev.objectif.activite"].sudo().search([
            ("id", "=", activite_id),
            ("goal_id", "in", self.goal_ids.ids),
        ], limit=1)
        if not activite:
            raise UserError(_(
                "Cette activité ne fait pas partie de la période en cours."))
        activite.unlink()

    def _objectif_de_la_periode(self, objectif_id):
        try:
            objectif_id = int(objectif_id or 0)
        except (TypeError, ValueError):
            objectif_id = 0
        objectif = self.goal_ids.filtered(lambda g: g.id == objectif_id)
        if not objectif:
            raise UserError(_(
                "Cet objectif ne fait pas partie de la période en cours."))
        return objectif

    def _ev_objectif_supprimer(self, objectif_id):
        """Retire un objectif de cette période.

        On ne retire QUE des objectifs de la période : un identifiant
        étranger, venu d'un formulaire trafiqué, ne doit rien pouvoir
        atteindre.
        """
        self.ensure_one()
        self._ev_check_ouverte()
        try:
            objectif_id = int(objectif_id or 0)
        except (TypeError, ValueError):
            objectif_id = 0
        objectif = self.goal_ids.filtered(lambda g: g.id == objectif_id)
        if not objectif:
            raise UserError(_(
                "Cet objectif ne fait pas partie de la période en cours."))
        if objectif.progression and objectif.progression != "000":
            raise UserError(_(
                "%s a déjà déclaré un avancement sur « %s » : l'objectif ne "
                "peut plus être retiré. Reformulez-le plutôt.",
                objectif.employee_id.name or "", objectif.name or ""))
        objectif.sudo().unlink()

    def _ev_objectif_avancement(self, employee, valeurs):
        """L'agent déclare où il en est. Il ne touche QU'À ses objectifs.

        L'avancement reste déclarable même période fermée : la période
        borne la FIXATION des objectifs, pas le suivi de l'année.
        """
        self.ensure_one()
        niveaux = dict(self.env["hr.appraisal.goal"]
                       ._fields["progression"].selection)
        for objectif in self._ev_objectifs_de(employee):
            brut = (valeurs.get("progress_%s" % objectif.id) or "").strip()
            if not brut:
                continue
            if brut not in niveaux:
                raise UserError(_(
                    "Avancement invalide pour « %s ».", objectif.name or ""))
            objectif.sudo().progression = brut

    @api.model
    def _periode_de_lexercice(self, exercice, company):
        """La période d'un exercice pour une société, s'il en existe une.

        C'est le seul point de jonction avec la campagne : on ne relie pas
        les deux objets par un lien direct, mais par l'exercice — la
        période est ouverte des mois avant que la campagne n'existe.
        """
        return self.search([
            ("exercice", "=", exercice),
            ("company_id", "=", company.id),
            ("state", "in", ("open", "closed")),
        ], limit=1)
