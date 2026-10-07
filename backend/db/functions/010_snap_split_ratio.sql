-- Turn a trade-price-to-close ratio into the split ratio it implies: 1 inside the band a normal
-- intraday move can explain, else the nearest whole ratio (n or 1/n) when that is within 12%,
-- else the raw ratio. Used to put ledger quantities onto the basis of split-adjusted prices.
CREATE OR REPLACE FUNCTION snap_split_ratio(ratio numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT CASE
        WHEN ratio >= 1.35 THEN
            CASE WHEN ABS(ROUND(ratio) / ratio - 1) <= 0.12 THEN ROUND(ratio) ELSE ratio END
        WHEN ratio <= 0.74 THEN
            CASE WHEN ABS((1 / ROUND(1 / ratio)) / ratio - 1) <= 0.12 THEN 1 / ROUND(1 / ratio) ELSE ratio END
        ELSE 1
    END
$$;
