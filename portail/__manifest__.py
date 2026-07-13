# -*- coding: utf-8 -*-
{
    "name": "Portail Employé (Self-Service)",
    "summary": "Espace self-service RH pour les employés via des utilisateurs Portail (gratuits).",
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.1.4.0",
    "license": "LGPL-3",
    "depends": ["portal", "website", "hr_payroll", "hr_holidays"],
    "data": [
        "views/portal_templates_home.xml",
        "views/portal_templates_payslip.xml",
        "views/portal_templates_leave.xml",
        "views/portal_templates_team.xml",
        "views/hr_employee_views.xml",
    ],
    "application": True,
    "installable": True,
}
