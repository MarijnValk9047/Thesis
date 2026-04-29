# DA Domain Codes

The day-ahead A01 price downloader uses these price-area codes:

- `NL`: `10YNL----------L`
- `BE`: `10YBE----------2`
- `DE`: `10Y1001A1001A82H`

Why these are used:
- the ENTSO-E A44 day-ahead price query is made at the price-area / bidding-zone level
- the raw XML files in this repo confirm the same values in both `in_Domain.mRID` and `out_Domain.mRID`
- for NL and BE the price-area code and the bidding-zone code are the same in this workflow
- for DE the price query uses `10Y1001A1001A82H`, while other datasets in the repo may use `10Y1001A1001A83F` for the DE bidding-zone / area context

Observed source check from the raw A01 XML:
- `NL` raw files contain `in_Domain = out_Domain = 10YNL----------L`
- `BE` raw files contain `in_Domain = out_Domain = 10YBE----------2`
- `DE` raw files contain `in_Domain = out_Domain = 10Y1001A1001A82H`

Conclusion:
- the current A01 DA price downloader is using the correct price-area level codes for the DA price query in this repo
- the separate DE bidding-zone code remains useful for other ENTSO-E query families, so both codes are documented explicitly
