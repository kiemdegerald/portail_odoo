# -*- coding: utf-8 -*-
{
    "name": "Gestion Recrutement (Site ↔ Odoo)",
    "summary": "Diffusion des offres et réception des candidatures depuis le "
               "site web externe, raccordées au pipeline de "
               "recrutement standard d'Odoo.",
    "description": """
Gestion Recrutement
==============================

Module complémentaire exposant deux passerelles HTTP entre l'instance Odoo
du site web :

* **Passerelle « aller »** : diffusion des offres publiées (hr.job) vers le site.
* **Passerelle « retour »** : réception des candidatures (hr.applicant) avec CV,
  rattachées à la bonne offre et injectées à l'étape initiale du pipeline
  de recrutement Odoo existant.

Le suivi du recrutement (entretiens, décisions, embauche) reste intégralement
géré par le module Recrutement standard : ce module ne le redéveloppe pas.
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources/Recruitment",
    "version": "17.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "hr_recruitment",
    ],
    "data": [
        "security/gr_security.xml",
        "security/ir.model.access.csv",
        "data/config_parameters.xml",
        "views/hr_job_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
    "auto_install": False,
}
