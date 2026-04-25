from rest_framework import serializers
from analysts.models import AnalystSignalRecord
from consensus.models import ConsensusSignal
from executor.models import Position, Trade, AccountState
from risk.models import RiskState, RiskEvent


class AnalystSignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalystSignalRecord
        fields = '__all__'


class ConsensusSignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsensusSignal
        fields = '__all__'


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


class RiskStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskState
        fields = '__all__'


class RiskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskEvent
        fields = '__all__'


class SystemStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    trading_mode = serializers.CharField()
    trading_pairs = serializers.ListField(child=serializers.CharField())
    ingester_active = serializers.BooleanField()
    total_candles = serializers.IntegerField()
    latest_candle_time = serializers.DateTimeField(allow_null=True)
    open_positions = serializers.IntegerField()
    daily_pnl = serializers.FloatField()
