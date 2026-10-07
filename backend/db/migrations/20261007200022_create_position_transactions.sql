-- migrate:up
-- Which ledger rows make up each position. Trades and corporate actions by quantity, income and
-- cost rows by the trade they were booked against (related_ref) or, unlinked, by date.
CREATE TABLE IF NOT EXISTS position_transactions (
    transaction_id bigint PRIMARY KEY REFERENCES ledger_transactions (id) ON DELETE CASCADE,
    position_id bigint NOT NULL REFERENCES positions (id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('trade', 'corporate_action', 'income', 'cost')),
    funding boolean NOT NULL DEFAULT FALSE,    -- a cost booked on a purchase: counts as invested cash
    basis_factor numeric(24, 12)               -- trades and corporate actions: quantity x this = adjusted shares
);

CREATE INDEX IF NOT EXISTS position_transactions_position_idx ON position_transactions (position_id);

-- migrate:down
DROP TABLE IF EXISTS position_transactions;
