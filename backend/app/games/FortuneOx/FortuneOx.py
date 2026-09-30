fortune_ox = {
    "name": "FortuneOx",
    "simulator" : {
        "host": "127.0.0.1",
        "port": 9090,
        "roi" : {
            "cash_meter": [0.0, 0.844468, 1.0, 0.884554],
            "cyclic_message": [0.0, 0.8475, 0.18, 0.8568],
            "cyclic_message_2": [0.0, 0.8568, 0.18, 0.867],
            "reels": [0.045131, 0.559722, 0.95487, 0.822222]
        },
        "logs" : "C:\\logs\\Game\\FortuneOx\\Logs\\FortuneOx_Client.log",
        "game_config" : "C:\\re\\games\\FortuneOx\\GameConfig",
        "win_geometry" : "C:\\re\\games\\FortuneOx\\GameConfig\\winGeometry.xml"
        },
    "egm" : {
        "host": "10.2.168.252",
        "port": 9090,
        "roi" : {
            "cash_meter": [0.241146, 0.866667, 0.757813, 1.0],
            "reels": [0.055208, 0.094444, 0.936979, 0.813889],
            "cyclic_message": [0.015625, 0.882407, 0.104167, 0.909259],
            "cyclic_message_2": [0.015625, 0.912963, 0.072917, 0.935185]
        },
        "logs" :  r"\\10.2.168.252\c$\wms_games\Logs\Game\FortuneOx\Logs\FortuneOx_Client.log",
        "game_config" : r"\\10.2.168.252\c$\games\FortuneOx\games\FortuneOx\GameConfig",
        "win_geometry" : r"\\10.2.168.252\c$\games\FortuneOx\games\FortuneOx\GameConfig\winGeometry.xml"
    },
    "symbols": {
        "WC": "WILD",
        "AA": "Ox",
        "BB": "Pisces",
        "CC": "Wealth Pot",
        "DD": "Arm Band",
        "EE": "Ace",
        "FF": "King",
        "GG": "Queen",
        "HH": "Jack",
        "JJ": "Ten",
        "MS": "Mystery1",
        "MO": "Mystery2",
        "MC": "Mystery (Orb)",
        "SC": "Orb",
        "SF": "Orb (Splittable)",
        "FG": "Free Games",
        "FO": "FO (feature)",
        "SO": "SO (feature)"
    },
    "scatter_symbols": ["SC", "FG", "SF"],
    # Weighted tables in math.xml that the Game Config tab shows as "Orb value range"; {bet} is
    # the paytable's minimum total bet. Negative values are jackpot levels (-5 is JP5).
    "orb_value_tables": [
        {"title": "Other orbs", "table": "BG_NonSCPearlCredit_{bet}"},
        {"title": "SC (scatter orb)", "table": "BG_SCPearlCredit_{bet}"},
    ],
    "meter": {
        "band": [0.138889, 0.555556]
    },

    "reel_bounds": {
        "rows": 3,
        "columns": 5,
        "inset": [0.055, 0.0]
    },
    "wild_card_replacement": [
        "AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "JJ"
    ],
    "gaf": {
        "game_type": "BallyStyle",
        "gdk_version": "12",
        "object_query_root": "app/games/FortuneOx/ObjectQuery.json",
        # The GAF tab's game-specific actions; spin, game state, denoms and meters are common to every game.
        "actions": [
            "take_win", "gamble", "toggle_credit_meter", "front_panel_messages", "unique_front_panel_messages",
        ],
    }
}