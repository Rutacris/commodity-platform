-- Reference data for the Kigali pilot.
-- Coordinates are approximate; replace with GPS taken at each market during Week 0.
-- Local-unit weights (std_per_price_unit) are placeholders until the Week 0 weighing study.
-- Kinyarwanda names are drafts pending native-speaker review.
INSERT INTO ref.markets (id, code, name, district, lat, lon) VALUES
 (1, 'NYB', 'Nyabugogo', 'Nyarugenge', -1.9386, 30.0446),
 (2, 'KIM', 'Kimironko', 'Gasabo',     -1.9496, 30.1260),
 (3, 'KAB', 'Kabuga',    'Gasabo',     -1.9757, 30.2279);

INSERT INTO ref.commodities (id, code, name_en, name_rw, name_fr, category, std_unit, price_unit, std_per_price_unit, perishable) VALUES
 ( 1, 'MAIZE',   'Maize grain',      'Ibigori byumye',        'Maïs grain',        'cereals',   'kg',    'kg',    1,   false),
 ( 2, 'MFLOUR',  'Maize flour',      'Kawunga',               'Farine de maïs',    'cereals',   'kg',    'kg',    1,   false),
 ( 3, 'RICE_L',  'Rice, local',      'Umuceri wo mu Rwanda',  'Riz local',         'cereals',   'kg',    'kg',    1,   false),
 ( 4, 'RICE_I',  'Rice, imported',   'Umuceri utumizwa hanze','Riz importé',       'cereals',   'kg',    'kg',    1,   false),
 ( 5, 'SORGHUM', 'Sorghum',          'Amasaka',               'Sorgho',            'cereals',   'kg',    'kg',    1,   false),
 ( 6, 'WFLOUR',  'Wheat flour',      'Ifu y''ingano',         'Farine de blé',     'cereals',   'kg',    'pack2kg', 2, false),
 ( 7, 'CFLOUR',  'Cassava flour',    'Ifu y''imyumbati',      'Farine de manioc',  'cereals',   'kg',    'kg',    1,   false),
 ( 8, 'BEANS',   'Beans, dry',       'Ibishyimbo',            'Haricots secs',     'pulses',    'kg',    'kg',    1,   false),
 ( 9, 'PEAS',    'Peas, dry',        'Amashaza',              'Petits pois secs',  'pulses',    'kg',    'kg',    1,   false),
 (10, 'GNUTS',   'Groundnuts',       'Ubunyobwa',             'Arachides',         'pulses',    'kg',    'kg',    1,   false),
 (11, 'IPOT',    'Irish potatoes',   'Ibirayi',               'Pommes de terre',   'roots',     'kg',    'kg',    1,   false),
 (12, 'SPOT',    'Sweet potatoes',   'Ibijumba',              'Patates douces',    'roots',     'kg',    'heap',  3,   true),
 (13, 'CASSAVA', 'Cassava, fresh',   'Imyumbati mibisi',      'Manioc frais',      'roots',     'kg',    'kg',    1,   true),
 (14, 'BANANA',  'Cooking bananas',  'Ibitoki',               'Bananes à cuire',   'roots',     'kg',    'kg',    1,   true),
 (15, 'TOMATO',  'Tomatoes',         'Inyanya',               'Tomates',           'vegetables','kg',    'basin', 4.5, true),
 (16, 'ONION',   'Onions',           'Ibitunguru',            'Oignons',           'vegetables','kg',    'kg',    1,   true),
 (17, 'CABBAGE', 'Cabbage',          'Amashu',                'Chou',              'vegetables','head',  'head',  1,   true),
 (18, 'CARROT',  'Carrots',          'Karoti',                'Carottes',          'vegetables','kg',    'kg',    1,   true),
 (19, 'EGGS',    'Eggs',             'Amagi',                 'Œufs',              'animal',    'egg',   'tray30',30,  false),
 (20, 'MILK',    'Milk, fresh',      'Amata',                 'Lait frais',        'animal',    'litre', 'litre', 1,   true),
 (21, 'BEEF',    'Beef',             'Inyama z''inka',        'Viande de bœuf',    'animal',    'kg',    'kg',    1,   true),
 (22, 'OIL',     'Cooking oil',      'Amavuta yo guteka',     'Huile de cuisine',  'other',     'litre', 'litre', 1,   false),
 (23, 'SUGAR',   'Sugar',            'Isukari',               'Sucre',             'other',     'kg',    'kg',    1,   false),
 (24, 'SALT',    'Salt',             'Umunyu',                'Sel',               'other',     'kg',    'kg',    1,   false);

INSERT INTO core.external_series (code, name, unit, frequency) VALUES
 ('DIESEL', 'Diesel pump price, Kigali', 'RWF/litre', 'monthly'),
 ('USDRWF', 'Exchange rate RWF per USD', 'RWF',       'daily'),
 ('RAIN_KGL', 'Rainfall, Kigali (district mean)', 'mm/day', 'daily'),
 ('BENCH_WFP', 'Benchmark Kigali food price index (WFP-like)', 'index', 'monthly');
