-- Exact product of NUMERIC values, used for split factors and for chaining daily returns into a
-- unit price. The state is rounded to 18 decimals each step so long chains stay bounded.
CREATE OR REPLACE FUNCTION numeric_product_step(acc numeric, value numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT ROUND(acc * value, 18)
$$;

CREATE OR REPLACE AGGREGATE numeric_product(numeric) (
    SFUNC = numeric_product_step,
    STYPE = numeric,
    INITCOND = '1'
);
