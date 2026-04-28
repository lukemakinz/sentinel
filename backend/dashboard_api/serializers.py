from rest_framework import serializers
from executor.models import Position, Trade, AccountState, ExchangeOpenOrder
from risk.models import RiskState, RiskEvent

# analysts/ and consensus/ removed from INSTALLED_APPS
# AnalystSignalSerializer and ConsensusSignalSerializer disabled


class PositionSerializer(serializers.ModelSerializer):
    pnl_percent = serializers.ReadOnlyField()

    class Meta:
        model = Position
        fields = '__all__'


class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = '__all__'


class AccountStateSerializer(serializers.ModelSerializer):
    win_rate = serializers.SerializerMethodField()

    class Meta:
        model = AccountState
        fields = '__all__'

    def get_win_rate(self, obj):
        if obj.total_trades > 0:
            return round(obj.winning_trades / obj.total_trades * 100, 1)
        return 0


class ExchangeOpenOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeOpenOrder
        fields = '__all__'


class RiskStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskState
        fields = '__all__'


class RiskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskEvent
        fields = '__all__'
