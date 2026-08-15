// AlphaDesk D0 bake-off — shared dataset. Derived from backend/tests/fixtures/demo/
// (synthetic fixture values; the 26-week history is invented for the demos).
const DATA = {
 "net_worth": 1007655.0,
 "gross": 1152655.0,
 "invested": 1063750.0,
 "liabilities": 145000.0,
 "overall_pnl": 88905.0,
 "overall_pct": 8.36,
 "by_asset_type": [
  {
   "label": "MF",
   "asset_type": "MF",
   "invested_amount": 258000.0,
   "current_value": 278410.0,
   "weight_pct": 24.2
  },
  {
   "label": "IND_STOCK",
   "asset_type": "IND_STOCK",
   "invested_amount": 283000.0,
   "current_value": 323905.0,
   "weight_pct": 28.1
  },
  {
   "label": "US_STOCK",
   "asset_type": "US_STOCK",
   "invested_amount": 96000.0,
   "current_value": 107590.0,
   "weight_pct": 9.3
  },
  {
   "label": "US_STOCK_WALLET",
   "asset_type": "US_STOCK_WALLET",
   "invested_amount": 18250,
   "current_value": 18250,
   "weight_pct": 1.6
  },
  {
   "label": "FD",
   "asset_type": "FD",
   "invested_amount": 240000.0,
   "current_value": 250000.0,
   "weight_pct": 21.7
  },
  {
   "label": "SA",
   "asset_type": "SA",
   "invested_amount": 86500.0,
   "current_value": 86500.0,
   "weight_pct": 7.5
  },
  {
   "label": "EPF",
   "asset_type": "EPF",
   "invested_amount": 82000.0,
   "current_value": 88000.0,
   "weight_pct": 7.6
  }
 ],
 "by_sector": [
  {
   "label": "Demo Sector Alpha",
   "invested_amount": 195000.0,
   "current_value": 222780.0,
   "weight_pct": 34.6
  },
  {
   "label": "Demo Sector Beta",
   "invested_amount": 88000.0,
   "current_value": 100512.5,
   "weight_pct": 15.6
  },
  {
   "label": "Demo Sector Gamma",
   "invested_amount": 96000.0,
   "current_value": 107590.0,
   "weight_pct": 16.7
  },
  {
   "label": "Demo Sector Delta",
   "invested_amount": 258000.0,
   "current_value": 278410.0,
   "weight_pct": 43.2
  }
 ],
 "by_market_cap": [
  {
   "label": "Demo Cap Band Large",
   "invested_amount": 451000.0,
   "current_value": 501187.5,
   "weight_pct": 77.8
  },
  {
   "label": "Demo Cap Band Mid",
   "invested_amount": 88000,
   "current_value": 100512,
   "weight_pct": 15.6
  },
  {
   "label": "Demo Cap Band Small",
   "invested_amount": 12000.0,
   "current_value": 0.0,
   "weight_pct": 0.0
  }
 ],
 "holdings": [
  {
   "id": "DEMO-MF-0001",
   "asset_type": "MF",
   "name": "Demo Alpha Largecap Fund",
   "symbol": null,
   "units": 2450.0,
   "invested": 180000.0,
   "current": 214497.5,
   "pnl": 34497.5,
   "pnl_pct": 19.17,
   "us": false
  },
  {
   "id": "DEMO-MF-0002",
   "asset_type": "MF",
   "name": "Demo Balanced Advantage Fund",
   "symbol": null,
   "units": 1500,
   "invested": null,
   "current": 63450,
   "pnl": null,
   "pnl_pct": null,
   "us": false
  },
  {
   "id": "DEMO-MF-0003",
   "asset_type": "MF",
   "name": "Demo Gamma Nano Fund",
   "symbol": null,
   "units": 0.0,
   "invested": 12000.0,
   "current": 0.0,
   "pnl": -12000.0,
   "pnl_pct": -100.0,
   "us": false
  },
  {
   "id": "DEMO-INDSTK-0001",
   "asset_type": "IND_STOCK",
   "name": "Demo Anvil Industries Ltd",
   "symbol": "DEMOANVIL",
   "units": 300.0,
   "invested": 195000.0,
   "current": 222780.0,
   "pnl": 27780.0,
   "pnl_pct": 14.25,
   "us": false
  },
  {
   "id": "DEMO-INDSTK-0002",
   "asset_type": "IND_STOCK",
   "name": "Demo Beacon Logistics Ltd",
   "symbol": "DEMOBEACON",
   "units": 850.0,
   "invested": 88000.0,
   "current": 100512.5,
   "pnl": 12512.5,
   "pnl_pct": 14.22,
   "us": false
  },
  {
   "id": "DEMO-USSTK-0001",
   "asset_type": "US_STOCK",
   "name": "Demo Orbital Systems Inc",
   "symbol": "DEMOORB",
   "units": 14.5,
   "invested": 96000.0,
   "current": 107590.0,
   "pnl": 11590.0,
   "pnl_pct": 12.07,
   "us": true
  },
  {
   "id": "DEMO-FD-0001",
   "asset_type": "FD",
   "name": "Demo Fixed Deposit 18M",
   "symbol": null,
   "units": null,
   "invested": 240000,
   "current": 250000,
   "pnl": 10000,
   "pnl_pct": 4.17,
   "us": false
  },
  {
   "id": "DEMO-SA-0001",
   "asset_type": "SA",
   "name": "Demo Savings Sweep",
   "symbol": null,
   "units": null,
   "invested": null,
   "current": 86500.0,
   "pnl": null,
   "pnl_pct": null,
   "us": false
  },
  {
   "id": "DEMO-WALLET-0001",
   "asset_type": "US_STOCK_WALLET",
   "name": "Demo US Wallet Cash",
   "symbol": null,
   "units": null,
   "invested": 18250.0,
   "current": 18250.0,
   "pnl": 0.0,
   "pnl_pct": 0.0,
   "us": true
  }
 ],
 "history": [
  {
   "week": 1,
   "label": "W1",
   "value": 874645.0
  },
  {
   "week": 2,
   "label": "W2",
   "value": 880690.0
  },
  {
   "week": 3,
   "label": "W3",
   "value": 877668.0
  },
  {
   "week": 4,
   "label": "W4",
   "value": 889759.0
  },
  {
   "week": 5,
   "label": "W5",
   "value": 901851.0
  },
  {
   "week": 6,
   "label": "W6",
   "value": 908905.0
  },
  {
   "week": 7,
   "label": "W7",
   "value": 897821.0
  },
  {
   "week": 8,
   "label": "W8",
   "value": 884721.0
  },
  {
   "week": 9,
   "label": "W9",
   "value": 880690.0
  },
  {
   "week": 10,
   "label": "W10",
   "value": 892782.0
  },
  {
   "week": 11,
   "label": "W11",
   "value": 905882.0
  },
  {
   "week": 12,
   "label": "W12",
   "value": 918981.0
  },
  {
   "week": 13,
   "label": "W13",
   "value": 928050.0
  },
  {
   "week": 14,
   "label": "W14",
   "value": 919989.0
  },
  {
   "week": 15,
   "label": "W15",
   "value": 911928.0
  },
  {
   "week": 16,
   "label": "W16",
   "value": 925027.0
  },
  {
   "week": 17,
   "label": "W17",
   "value": 941150.0
  },
  {
   "week": 18,
   "label": "W18",
   "value": 954249.0
  },
  {
   "week": 19,
   "label": "W19",
   "value": 948203.0
  },
  {
   "week": 20,
   "label": "W20",
   "value": 962311.0
  },
  {
   "week": 21,
   "label": "W21",
   "value": 975410.0
  },
  {
   "week": 22,
   "label": "W22",
   "value": 988510.0
  },
  {
   "week": 23,
   "label": "W23",
   "value": 979441.0
  },
  {
   "week": 24,
   "label": "W24",
   "value": 993548.0
  },
  {
   "week": 25,
   "label": "W25",
   "value": 1004632.0
  },
  {
   "week": 26,
   "label": "W26",
   "value": 1007655.0
  }
 ],
 "empty_types": [
  "EPF"
 ]
};
