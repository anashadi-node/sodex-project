# Focused scientific stats: unique-source, no JSONL double count

## data/paper_test_realwide_state.json
- rows=159 pnl_rows=159
- ALL: n=159 WR=52.2% total=+1.0395 mean=+0.0065 PF=1.46 CI95=[-0.0003,+0.0138] P>0=97.1%
- TRACK ?: n=159 WR=52.2% total=+1.0395 mean=+0.0065 PF=1.46 CI95=[-0.0005,+0.0139] P>0=96.7%

### Exit reason
- ?: n=159 WR=52.2% total=+1.0395 mean=+0.0065 PF=1.46 CI95=[-0.0010,+0.0139] P>0=95.9%

### Symbol worst/best n>=5
- WORST SUI: n=7 WR=14.3% total=-0.1962 mean=-0.0280 PF=0.03 CI95=[-0.0358,-0.0161] P>0=0.0%
- WORST ADA: n=6 WR=33.3% total=-0.1407 mean=-0.0234 PF=0.06 CI95=[-0.0399,-0.0070] P>0=0.2%
- WORST ONDO: n=6 WR=33.3% total=-0.1169 mean=-0.0195 PF=0.09 CI95=[-0.0325,-0.0063] P>0=0.3%
- WORST HYPE: n=6 WR=33.3% total=-0.0996 mean=-0.0166 PF=0.27 CI95=[-0.0363,+0.0060] P>0=7.2%
- WORST BCH: n=6 WR=50.0% total=-0.0760 mean=-0.0127 PF=0.18 CI95=[-0.0253,+0.0005] P>0=2.9%
- WORST XRP: n=6 WR=50.0% total=-0.0636 mean=-0.0106 PF=0.22 CI95=[-0.0238,+0.0017] P>0=5.8%
- WORST DOGE: n=8 WR=25.0% total=-0.0593 mean=-0.0074 PF=0.67 CI95=[-0.0315,+0.0306] P>0=29.6%
- WORST SILVER: n=5 WR=40.0% total=-0.0545 mean=-0.0109 PF=0.11 CI95=[-0.0235,+0.0017] P>0=4.6%
- WORST TRX: n=5 WR=20.0% total=-0.0298 mean=-0.0060 PF=0.33 CI95=[-0.0146,+0.0051] P>0=12.4%
- WORST ARB: n=6 WR=33.3% total=-0.0043 mean=-0.0007 PF=0.98 CI95=[-0.0444,+0.0455] P>0=44.6%
- BEST SOL: n=17 WR=64.7% total=+0.5116 mean=+0.0301 PF=4.28 CI95=[+0.0062,+0.0525] P>0=99.3%
- BEST UNI: n=12 WR=66.7% total=+0.3988 mean=+0.0332 PF=3.65 CI95=[-0.0004,+0.0675] P>0=97.4%
- BEST ETH: n=17 WR=70.6% total=+0.2182 mean=+0.0128 PF=2.79 CI95=[-0.0032,+0.0303] P>0=93.7%
- BEST BTC: n=13 WR=53.8% total=+0.1874 mean=+0.0144 PF=2.58 CI95=[-0.0066,+0.0365] P>0=90.6%
- BEST AVAX: n=7 WR=71.4% total=+0.1362 mean=+0.0195 PF=4.40 CI95=[-0.0097,+0.0568] P>0=86.2%
- BEST BNB: n=7 WR=71.4% total=+0.0720 mean=+0.0103 PF=2.04 CI95=[-0.0185,+0.0485] P>0=68.2%
- BEST AAVE: n=5 WR=60.0% total=+0.0490 mean=+0.0098 PF=1.62 CI95=[-0.0307,+0.0503] P>0=70.4%
- BEST ENA: n=5 WR=60.0% total=+0.0434 mean=+0.0087 PF=1.54 CI95=[-0.0314,+0.0629] P>0=61.8%
- BEST ASTER: n=9 WR=55.6% total=+0.0037 mean=+0.0004 PF=1.03 CI95=[-0.0234,+0.0336] P>0=47.4%
- BEST ARB: n=6 WR=33.3% total=-0.0043 mean=-0.0007 PF=0.98 CI95=[-0.0444,+0.0455] P>0=44.6%

## data/paper_test_shortbear_state.json
- rows=15 pnl_rows=15
- ALL: n=15 WR=66.7% total=-0.0080 mean=-0.0005 PF=0.88 CI95=[-0.0052,+0.0040] P>0=42.6%
- TRACK ?: n=15 WR=66.7% total=-0.0080 mean=-0.0005 PF=0.88 CI95=[-0.0054,+0.0038] P>0=42.2%

### Exit reason
- ?: n=15 WR=66.7% total=-0.0080 mean=-0.0005 PF=0.88 CI95=[-0.0054,+0.0039] P>0=43.1%

### Symbol worst/best n>=5

## data/paper_test_spot_swing_cex.json
- rows=401 pnl_rows=401
- ALL: n=401 WR=41.6% total=+0.6223 mean=+0.0016 PF=1.20 CI95=[-0.0004,+0.0035] P>0=93.9%
- TRACK SIGNAL: n=189 WR=40.7% total=+0.3164 mean=+0.0017 PF=1.23 CI95=[-0.0009,+0.0043] P>0=88.6%
- TRACK RANDOM: n=212 WR=42.5% total=+0.3058 mean=+0.0014 PF=1.18 CI95=[-0.0013,+0.0042] P>0=85.1%
- Δ SIGNAL-RANDOM mean=+0.0002 CI95=[-0.0036,+0.0040] permutation_p=0.9096

### Exit reason
- TP: n=135 WR=100.0% total=+3.4304 mean=+0.0254 PF=inf CI95=[+0.0239,+0.0270] P>0=100.0%
- TIME_STOP: n=59 WR=54.2% total=+0.1517 mean=+0.0026 PF=1.98 CI95=[-0.0000,+0.0053] P>0=97.4%
- SYSTEM_UPGRADE: n=6 WR=0.0% total=+0.0000 mean=+0.0000 PF=0.00 CI95=[+0.0000,+0.0000] P>0=0.0%
- EMERGENCY_SL: n=93 WR=0.0% total=-1.0468 mean=-0.0113 PF=0.00 CI95=[-0.0122,-0.0103] P>0=0.0%
- SL: n=108 WR=0.0% total=-1.9130 mean=-0.0177 PF=0.00 CI95=[-0.0186,-0.0169] P>0=0.0%

### Symbol worst/best n>=5
- WORST NEAR: n=16 WR=25.0% total=-0.0653 mean=-0.0041 PF=0.58 CI95=[-0.0117,+0.0042] P>0=14.6%
- WORST NVDA: n=5 WR=0.0% total=-0.0650 mean=-0.0130 PF=0.00 CI95=[-0.0168,-0.0088] P>0=0.0%
- WORST ADA: n=31 WR=38.7% total=-0.0612 mean=-0.0020 PF=0.80 CI95=[-0.0085,+0.0050] P>0=28.9%
- WORST LINK: n=24 WR=25.0% total=-0.0595 mean=-0.0025 PF=0.72 CI95=[-0.0089,+0.0049] P>0=23.8%
- WORST ZEC: n=22 WR=31.8% total=-0.0549 mean=-0.0025 PF=0.79 CI95=[-0.0118,+0.0078] P>0=31.6%
- WORST ENA: n=13 WR=30.8% total=-0.0508 mean=-0.0039 PF=0.65 CI95=[-0.0137,+0.0077] P>0=23.4%
- WORST XAUT: n=7 WR=14.3% total=-0.0159 mean=-0.0023 PF=0.36 CI95=[-0.0062,+0.0023] P>0=14.7%
- WORST UNI: n=13 WR=38.5% total=+0.0072 mean=+0.0006 PF=1.05 CI95=[-0.0112,+0.0141] P>0=53.5%
- WORST SUI: n=8 WR=37.5% total=+0.0090 mean=+0.0011 PF=1.13 CI95=[-0.0124,+0.0168] P>0=52.5%
- WORST BCH: n=17 WR=29.4% total=+0.0097 mean=+0.0006 PF=1.07 CI95=[-0.0084,+0.0104] P>0=52.7%
- BEST BTC: n=31 WR=54.8% total=+0.1375 mean=+0.0044 PF=1.93 CI95=[-0.0008,+0.0096] P>0=94.9%
- BEST DOGE: n=27 WR=59.3% total=+0.1240 mean=+0.0046 PF=1.76 CI95=[-0.0024,+0.0113] P>0=90.8%
- BEST LIT: n=5 WR=60.0% total=+0.1192 mean=+0.0238 PF=4.65 CI95=[-0.0040,+0.0517] P>0=91.7%
- BEST ETH: n=26 WR=53.8% total=+0.1054 mean=+0.0041 PF=1.67 CI95=[-0.0027,+0.0106] P>0=88.6%
- BEST PENDLE: n=11 WR=45.5% total=+0.1046 mean=+0.0095 PF=2.67 CI95=[-0.0043,+0.0239] P>0=90.7%
- BEST HYPE: n=18 WR=50.0% total=+0.0913 mean=+0.0051 PF=1.79 CI95=[-0.0041,+0.0137] P>0=86.8%
- BEST SOL: n=33 WR=39.4% total=+0.0661 mean=+0.0020 PF=1.29 CI95=[-0.0037,+0.0078] P>0=74.9%
- BEST AAVE: n=11 WR=54.5% total=+0.0589 mean=+0.0054 PF=1.93 CI95=[-0.0048,+0.0152] P>0=84.4%
- BEST PUMP: n=9 WR=44.4% total=+0.0565 mean=+0.0063 PF=1.79 CI95=[-0.0112,+0.0240] P>0=74.2%
- BEST XRP: n=17 WR=52.9% total=+0.0342 mean=+0.0020 PF=1.25 CI95=[-0.0075,+0.0111] P>0=66.7%

## data/paper_test_spot_swing_cex_spot.json
- rows=102 pnl_rows=102
- ALL: n=102 WR=30.4% total=-0.1368 mean=-0.0013 PF=0.86 CI95=[-0.0057,+0.0030] P>0=27.7%
- TRACK RANDOM: n=46 WR=37.0% total=+0.0367 mean=+0.0008 PF=1.08 CI95=[-0.0060,+0.0081] P>0=57.8%
- TRACK SIGNAL: n=56 WR=25.0% total=-0.1735 mean=-0.0031 PF=0.69 CI95=[-0.0083,+0.0026] P>0=14.1%
- Δ SIGNAL-RANDOM mean=-0.0039 CI95=[-0.0128,+0.0052] permutation_p=0.3836

### Exit reason
- TP: n=25 WR=100.0% total=+0.8072 mean=+0.0323 PF=inf CI95=[+0.0266,+0.0380] P>0=100.0%
- SYSTEM_UPGRADE: n=3 WR=0.0% total=+0.0000 mean=+0.0000 PF=0.00 CI95=[+0.0000,+0.0000] P>0=0.0%
- TIME_STOP: n=16 WR=37.5% total=-0.0259 mean=-0.0016 PF=0.68 CI95=[-0.0070,+0.0039] P>0=27.2%
- SL: n=19 WR=0.0% total=-0.4474 mean=-0.0235 PF=0.00 CI95=[-0.0282,-0.0190] P>0=0.0%
- EMERGENCY_SL: n=39 WR=0.0% total=-0.4707 mean=-0.0121 PF=0.00 CI95=[-0.0135,-0.0106] P>0=0.0%

### Symbol worst/best n>=5
- WORST DOGE: n=6 WR=16.7% total=-0.1119 mean=-0.0186 PF=0.15 CI95=[-0.0308,-0.0021] P>0=1.2%
- WORST SOL: n=9 WR=22.2% total=-0.0381 mean=-0.0042 PF=0.42 CI95=[-0.0102,+0.0027] P>0=11.3%
- WORST ETH: n=8 WR=37.5% total=-0.0379 mean=-0.0047 PF=0.41 CI95=[-0.0129,+0.0037] P>0=13.6%
- WORST LINK: n=5 WR=20.0% total=-0.0338 mean=-0.0068 PF=0.51 CI95=[-0.0232,+0.0148] P>0=23.4%
- WORST BTC: n=7 WR=28.6% total=-0.0336 mean=-0.0048 PF=0.32 CI95=[-0.0102,+0.0024] P>0=9.9%
- WORST PENDLE: n=6 WR=16.7% total=-0.0282 mean=-0.0047 PF=0.60 CI95=[-0.0164,+0.0149] P>0=26.7%
- WORST BCH: n=6 WR=16.7% total=-0.0161 mean=-0.0027 PF=0.68 CI95=[-0.0116,+0.0127] P>0=27.5%
- WORST XRP: n=9 WR=33.3% total=-0.0052 mean=-0.0006 PF=0.92 CI95=[-0.0103,+0.0098] P>0=45.3%
- WORST AVAX: n=5 WR=40.0% total=+0.0042 mean=+0.0008 PF=1.13 CI95=[-0.0135,+0.0152] P>0=55.7%
- WORST ADA: n=6 WR=33.3% total=+0.0326 mean=+0.0054 PF=1.64 CI95=[-0.0133,+0.0266] P>0=65.3%
- BEST ZEC: n=8 WR=50.0% total=+0.1205 mean=+0.0151 PF=2.45 CI95=[-0.0104,+0.0412] P>0=87.3%
- BEST ADA: n=6 WR=33.3% total=+0.0326 mean=+0.0054 PF=1.64 CI95=[-0.0133,+0.0266] P>0=65.3%
- BEST AVAX: n=5 WR=40.0% total=+0.0042 mean=+0.0008 PF=1.13 CI95=[-0.0135,+0.0152] P>0=55.7%
- BEST XRP: n=9 WR=33.3% total=-0.0052 mean=-0.0006 PF=0.92 CI95=[-0.0103,+0.0098] P>0=45.3%
- BEST BCH: n=6 WR=16.7% total=-0.0161 mean=-0.0027 PF=0.68 CI95=[-0.0116,+0.0127] P>0=27.5%
- BEST PENDLE: n=6 WR=16.7% total=-0.0282 mean=-0.0047 PF=0.60 CI95=[-0.0164,+0.0149] P>0=26.7%
- BEST BTC: n=7 WR=28.6% total=-0.0336 mean=-0.0048 PF=0.32 CI95=[-0.0102,+0.0024] P>0=9.9%
- BEST LINK: n=5 WR=20.0% total=-0.0338 mean=-0.0068 PF=0.51 CI95=[-0.0232,+0.0148] P>0=23.4%
- BEST ETH: n=8 WR=37.5% total=-0.0379 mean=-0.0047 PF=0.41 CI95=[-0.0129,+0.0037] P>0=13.6%
- BEST SOL: n=9 WR=22.2% total=-0.0381 mean=-0.0042 PF=0.42 CI95=[-0.0102,+0.0027] P>0=11.3%
