-- =====================================================================================
-- 02_reference_data.sql
-- Purpose : analyst-maintained mapping tables that standardise the council's labels.
--           Every mapping lives here (not buried in code) so it can be reviewed and extended.
--           Anything unmapped falls through to 'Unmapped' and is surfaced by the data-quality checks.
-- Creates : ref_spend_category, ref_department, ref_service_area
-- =====================================================================================

-- ---- Spend category -> clean label + analyst-defined theme (9 themes) -----------------
DROP TABLE IF EXISTS ref_spend_category;
CREATE TABLE ref_spend_category (
    spend_category_raw   TEXT PRIMARY KEY,
    spend_category_clean TEXT NOT NULL,
    spend_theme          TEXT NOT NULL
);
INSERT INTO ref_spend_category VALUES
 ('Suppliers - Social community care/Healthcare',        'Social, community care & healthcare',    'Social care & health'),
 ('Suppliers - Care Providers',                          'Care providers',                         'Social care & health'),
 ('Foster Carers',                                       'Foster carers',                          'Social care & health'),
 ('Suppliers -Public Health',                            'Public health',                          'Social care & health'),
 ('Suppliers - Education & Sports',                      'Education & sports',                     'Education & children'),
 ('Suppliers - Accomodation (Housing)',                  'Accommodation (housing)',                'Housing & construction'),
 ('Construction Industry suppliers (CIS)',               'Construction industry suppliers (CIS)',  'Housing & construction'),
 ('Suppliers - Professional Services (consultants)',     'Professional services (consultants)',    'Corporate, finance & legal'),
 ('Suppliers - Financial Services',                      'Financial services',                     'Corporate, finance & legal'),
 ('Suppliers - Legal (Excl Counsel Fees)',               'Legal (excl. counsel fees)',             'Corporate, finance & legal'),
 ('Legal counsel fees',                                  'Legal counsel fees',                     'Corporate, finance & legal'),
 ('Suppliers - Human Resources',                         'Human resources',                        'Workforce'),
 ('Suppliers - Agency staff',                            'Agency staff',                           'Workforce'),
 ('LBH Employees/Pensions',                              'Employees / pensions',                   'Workforce'),
 ('Suppliers - ICT Hardware/Software/Networks etc',      'ICT hardware, software & networks',      'ICT & digital'),
 ('Suppliers - Utilities',                               'Utilities',                              'Environment, transport & utilities'),
 ('Suppliers - Vehicles/Transport',                      'Vehicles & transport',                   'Environment, transport & utilities'),
 ('Suppliers - Environmental Services',                  'Environmental services',                 'Environment, transport & utilities'),
 ('Suppliers - Traffic management/Highways',             'Traffic management & highways',          'Environment, transport & utilities'),
 ('Suppliers - Grounds Maintenance',                     'Grounds maintenance',                    'Environment, transport & utilities'),
 ('External - Grants/Allowances',                        'Grants & allowances',                    'Grants, voluntary & public bodies'),
 ('Voluntary organisations',                             'Voluntary organisations',                'Grants, voluntary & public bodies'),
 ('Local Authorities/Central Government',                'Local authorities / central government', 'Grants, voluntary & public bodies'),
 ('Intercompany Lampton group Suppliers',                'Intercompany (council group)',           'Grants, voluntary & public bodies'),
 ('External - Homes for Ukraine',                        'Homes for Ukraine',                      'Grants, voluntary & public bodies'),
 ('Suppliers - General Goods & Services',                'General goods & services',               'General goods & services'),
 ('Suppliers - Facilities Management/Mail/Clothing',     'Facilities management, mail & clothing', 'General goods & services'),
 ('Suppliers - Advertising/Events/Publicity',            'Advertising, events & publicity',        'General goods & services'),
 ('Suppliers - Catering',                                'Catering',                               'General goods & services'),
 ('Suppliers - Retail',                                  'Retail',                                 'General goods & services'),
 ('Suppliers - Office Supplies',                         'Office supplies',                        'General goods & services'),
 ('External - Interface Sundry Suppliers (excl Refunds)','Sundry suppliers (excl. refunds)',       'General goods & services');

-- ---- Department (directorate) --------------------------------------------------------
-- Clean directorate + whether the line is Capital or Revenue/HRA expenditure.
-- The council re-organised during the period, so some directorate names are legitimately
-- different rather than misspelt; those are kept distinct and only cosmetic variants are merged.
DROP TABLE IF EXISTS ref_department;
CREATE TABLE ref_department (
    department_raw   TEXT PRIMARY KEY,
    directorate      TEXT NOT NULL,
    expenditure_type TEXT NOT NULL     -- Revenue | Capital | HRA | HRA Capital
);
INSERT INTO ref_department VALUES
 ('CHILDRENS AND ADULT SERVICES',                           'Childrens and Adult Services',                    'Revenue'),
 ('CAPITAL CHILDRENS AND ADULT SERVICES',                   'Childrens and Adult Services',                    'Capital'),
 ('REGENERATION, HOUSING & ENVIRONMENTAL SERVICES',         'Regeneration, Housing and Environmental Services','Revenue'),
 ('CAPITAL REGENERATION, HOUSING & ENVIRONMENTAL SERVICES', 'Regeneration, Housing and Environmental Services','Capital'),
 ('HOUSING REVENUE ACCOUNT',                                'Housing Revenue Account',                         'HRA'),
 ('CAPITAL HRA',                                            'Housing Revenue Account',                         'HRA Capital'),
 ('RESOURCES',                                              'Resources',                                       'Revenue'),
 ('CAPITAL RESOURCES',                                      'Resources',                                       'Capital'),
 ('COMMUNITY & STRATEGY',                                   'Community and Strategy',                          'Revenue'),
 ('CAPITAL COMMUNITY & STRATEGY',                           'Community and Strategy',                          'Capital'),
 ('CAPITAL COMMUNITY',                                      'Community and Strategy',                          'Capital'),
 ('PLACEMAKING AND GROWTH',                                 'Placemaking and Growth',                          'Revenue'),
 ('PLACEMAKING & GROWTH',                                   'Placemaking and Growth',                          'Revenue'),
 ('CAPITAL PLACEMAKING AND GROWTH',                         'Placemaking and Growth',                          'Capital'),
 ('ICP, HEALTH & SOCIAL CARE INTEGRATION',                  'ICP, Health and Social Care Integration',         'Revenue'),
 ('WELLBEING, ENVIRONMENT AND COMMISSIONING',               'Wellbeing, Environment and Commissioning',        'Revenue'),
 ('CAPITAL WELLBEING, ENVIRONMENT AND COMMISSIONING',       'Wellbeing, Environment and Commissioning',        'Capital'),
 ('STRATEGY & TRANSFORMATION',                              'Strategy and Transformation',                     'Revenue'),
 ('STRATEGY, DIGITAL & TRANSFORMATION',                     'Strategy, Digital and Transformation',            'Revenue'),
 ('CAPITAL STRATEGY, DIGITAL & TRANSFORMATION',             'Strategy, Digital and Transformation',            'Capital'),
 ('FINANCE, RESOURCES & ASSETS',                            'Finance, Resources and Assets',                   'Revenue'),
 ('CAPITAL FINANCE, RESOURCES AND ASSETS',                  'Finance, Resources and Assets',                   'Capital'),
 ('COMMUNITIES',                                            'Communities',                                     'Revenue'),
 ('CHIEF EXECUTIVE',                                        'Chief Executive',                                 'Revenue'),
 ('DELIVERY PLAN',                                          'Delivery Plan',                                   'Revenue'),
 ('REVENUE ON IE ACCOUNT',                                  'Revenue on IE Account',                           'Revenue'),
 ('SCHOOLS - NON DELEGATED & DELEGATED',                    'Schools (delegated and non-delegated)',           'Revenue');

-- ---- Service area: fix typos and synonyms only ---------------------------------------
DROP TABLE IF EXISTS ref_service_area;
CREATE TABLE ref_service_area (
    service_area_raw   TEXT PRIMARY KEY,
    service_area_clean TEXT NOT NULL
);
INSERT INTO ref_service_area VALUES
 ('Children''s and Education Services',    'Children''s and Education Services'),
 ('Housing Services',                      'Housing Services'),
 ('Housing Revenue Account',               'Housing Revenue Account'),
 ('Revenue Recharges',                     'Revenue Recharges'),
 ('Housing',                               'Housing'),
 ('Adult Social Care',                     'Adult Social Care'),
 ('Environmental and Regualtory Services', 'Environmental and Regulatory Services'),  -- source typo
 ('Public Health',                         'Public Health'),
 ('Highways and Transport Services',       'Highways and Transport Services'),
 ('Planning Services',                     'Planning Services'),
 ('Central Services',                      'Central Services'),
 ('Cultural and Related Services',         'Cultural and Related Services'),
 ('Culture & Related Services',            'Cultural and Related Services'),          -- synonym
 ('Other Non Distributed Costs',           'Other Non Distributed Costs'),
 ('Transport',                             'Transport'),
 ('Education',                             'Education'),
 ('Corporate and Democratic Core',         'Corporate and Democratic Core'),
 ('Social Services',                       'Social Services'),
 ('Environmental Services',                'Environmental Services'),
 ('Planning & Development',                'Planning & Development');
