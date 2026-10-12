-- Distribution and the way a value was determined, for the lines added by users to the uncertainty budget.
ALTER TABLE uncertainty_settings ADD COLUMN IF NOT EXISTS dist text CHECK (dist IS NULL OR dist IN ('normal', 'uniform', 'triangular', 'ushaped'));
ALTER TABLE uncertainty_settings ADD COLUMN IF NOT EXISTS how text;
