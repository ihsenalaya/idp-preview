-- Default seed data for idp-preview demo
-- Run with: psql $DATABASE_URL -f seeds/default/seed.sql

BEGIN;

-- Categories
INSERT INTO categories (name, slug, description) VALUES
  ('Electronics',  'electronics',  'Gadgets and electronic devices'),
  ('Books',        'books',        'Technical and non-fiction books'),
  ('Clothing',     'clothing',     'Apparel and accessories'),
  ('Home & Garden','home-garden',  'Home improvement and gardening'),
  ('Sports',       'sports',       'Sports equipment and activewear')
ON CONFLICT (slug) DO NOTHING;

-- Products
INSERT INTO products (name, slug, description, price, stock, discount_percent, category_id)
SELECT
  p.name, p.slug, p.description, p.price, p.stock, p.discount_percent, c.id
FROM (VALUES
  ('Wireless Headphones', 'wireless-headphones', 'Noise-cancelling Bluetooth headphones', 149.99, 25, 10.0, 'electronics'),
  ('Mechanical Keyboard', 'mechanical-keyboard', 'Tenkeyless mechanical keyboard with RGB', 89.99, 40, 0.0,  'electronics'),
  ('USB-C Hub',           'usb-c-hub',           '7-port USB-C hub with PD charging',      39.99, 60, 15.0, 'electronics'),
  ('Clean Code',          'clean-code',           'Robert C. Martin — software craftsmanship', 34.99, 15, 0.0, 'books'),
  ('The Phoenix Project', 'phoenix-project',      'Gene Kim — DevOps novel',                29.99, 20, 5.0,  'books'),
  ('Running Shoes',       'running-shoes',        'Lightweight marathon training shoes',     79.99, 30, 20.0, 'sports'),
  ('Yoga Mat',            'yoga-mat',             'Non-slip 6mm yoga mat',                  24.99, 50, 0.0,  'sports'),
  ('Desk Lamp',           'desk-lamp',            'LED desk lamp with wireless charging',    44.99, 35, 10.0, 'home-garden'),
  ('Thermal Mug',         'thermal-mug',          'Double-wall stainless steel travel mug',  19.99, 80, 0.0,  'home-garden'),
  ('Dev T-Shirt',         'dev-tshirt',           '"Hello, World!" organic cotton t-shirt',  24.99, 100, 30.0, 'clothing')
) AS p(name, slug, description, price, stock, discount_percent, cat_slug)
JOIN categories c ON c.slug = p.cat_slug
ON CONFLICT (slug) DO NOTHING;

-- Reviews
INSERT INTO reviews (product_id, rating, comment, author)
SELECT p.id, r.rating, r.comment, r.author
FROM (VALUES
  ('wireless-headphones', 5, 'Excellent sound quality, very comfortable', 'alice'),
  ('wireless-headphones', 4, 'Great battery life, slight bass boost',     'bob'),
  ('mechanical-keyboard', 5, 'Perfect actuation, very satisfying to type','carol'),
  ('clean-code',          5, 'Changed how I write code forever',          'dave'),
  ('running-shoes',       4, 'Lightweight and responsive',                'eve'),
  ('yoga-mat',            3, 'Good grip but a bit thin',                  'frank')
) AS r(slug, rating, comment, author)
JOIN products p ON p.slug = r.slug
ON CONFLICT DO NOTHING;

-- A sample pending order
INSERT INTO orders (product_id, quantity, status)
SELECT p.id, 1, 'pending'
FROM products p WHERE p.slug = 'wireless-headphones'
ON CONFLICT DO NOTHING;

COMMIT;
