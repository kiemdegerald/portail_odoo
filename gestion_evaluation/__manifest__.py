# -*- coding: utf-8 -*-
{
    "name": "Gestion des Évaluations",
    "summary": "Campagnes d'évaluation annuelle du personnel : ciblage, "
               "génération en masse, circuit de validation et grille de "
               "notation configurable.",
    "description": """
Gestion des Évaluations
=======================

Complète le module **Évaluations** standard d'Odoo, qui raisonne évaluation
par évaluation, avec ce qui lui manque :

* la **campagne annuelle** : ciblage d'une population, génération en masse
  des évaluations, tableau de bord d'avancement, clôture ;
* le **circuit de validation** à plusieurs phases, dont la **validation
  N+2** absente du standard ;
* les **objectifs rattachés à leur exercice**, jamais mélangés d'une année
  sur l'autre ;
* la **grille de notation configurable** : des rubriques qui s'emboîtent,
  des critères qu'on note, un poids sur chaque ligne.

Le module ne redéveloppe PAS l'évaluation : il pilote les évaluations
standard d'Odoo (``hr.appraisal``), qui conservent l'intégralité de leur
comportement natif (feedbacks, compétences, entretien, 360°).
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.0.73.0",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "hr_appraisal",
        # L'entretien annuel est posé comme un vrai rendez-vous
        # (``calendar.event``) : c'est de là qu'Odoo tire la date
        # d'entretien de l'évaluation.
        "calendar",
    ],
    "data": [
        "security/ev_security.xml",
        "security/ir.model.access.csv",
        "data/ev_circuit_data.xml",
        "data/ev_grille_data.xml",
        "data/ev_taux_note_data.xml",
        "data/ev_grille_badf_data.xml",
        "views/ev_grille_views.xml",
        "views/ev_taux_note_views.xml",
        "views/ev_circuit_views.xml",
        "views/ev_settings_views.xml",
        "views/ev_periode_objectifs_views.xml",
        "views/ev_campagne_views.xml",
        "views/hr_appraisal_views.xml",
        "views/hr_appraisal_goal_views.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
