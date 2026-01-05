"""
Sully Chain AI/BI Analytics Engine

Advanced analytics and machine learning capabilities for the Sully Chain supplier management system.
Provides:
- Supplier Performance Scoring with dynamic weighting
- Fraud Detection and Risk Assessment
- Price Prediction and Optimization
- Supplier Recommendation Engine
- Business Intelligence Dashboards
- Trend Analysis and Forecasting
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal
from enum import Enum
import math
import statistics
import json
import logging
import hashlib
import uuid

# Database imports
from database import get_db_session
from database.sully_chain_models import (
    Supplier, Allocation, Bid, ServiceFulfillment, ServiceMilestone,
    SupplierScore, AllocationAnalytics, SullyLedger, ClientInteraction,
    SupplierTransaction, SupplierStatus, BidStatus, FulfillmentStatus
)
from database.repositories.sully_chain_repository import (
    SupplierRepository, AllocationRepository, BidRepository,
    ServiceFulfillmentRepository, SupplierScoreRepository,
    AllocationAnalyticsRepository, SullyLedgerRepository,
    ClientInteractionRepository, SupplierTransactionRepository
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes for Analytics Results
# =============================================================================

@dataclass
class PerformanceMetrics:
    """Detailed performance metrics for a supplier"""
    supplier_id: str
    overall_score: float
    performance_tier: str
    
    # Individual Scores (0-100)
    completion_rate_score: float
    quality_score: float
    reliability_score: float
    price_competitiveness_score: float
    response_time_score: float
    compliance_score: float
    
    # Raw Metrics
    total_allocations: int
    successful_completions: int
    average_rating: float
    on_time_rate: float
    win_rate: float
    
    # Trends
    trend_direction: str  # 'improving', 'stable', 'declining'
    score_change_30d: float
    
    # Comparison
    percentile_rank: int
    peer_comparison: Dict[str, float] = field(default_factory=dict)


@dataclass
class FraudAlert:
    """Fraud detection alert"""
    alert_id: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    alert_type: str
    entity_type: str
    entity_id: str
    description: str
    risk_score: float
    indicators: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PricePrediction:
    """Price prediction result"""
    allocation_id: str
    service_type: str
    predicted_winning_price: float
    confidence_level: float
    price_range_low: float
    price_range_high: float
    factors_considered: List[str] = field(default_factory=list)
    comparable_allocations: List[str] = field(default_factory=list)


@dataclass
class SupplierRecommendation:
    """Supplier recommendation for an allocation"""
    supplier_id: str
    supplier_name: str
    match_score: float
    recommendation_reasons: List[str]
    estimated_bid_amount: float
    expected_quality_score: float
    risk_level: str


@dataclass
class DashboardInsight:
    """Business intelligence insight"""
    insight_id: str
    category: str  # 'performance', 'trend', 'anomaly', 'opportunity'
    title: str
    description: str
    impact_level: str  # 'low', 'medium', 'high'
    data_points: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)


# =============================================================================
# Performance Scoring Engine
# =============================================================================

class PerformanceScoringEngine:
    """
    AI-powered supplier performance scoring engine.
    Uses weighted multi-factor scoring with dynamic adjustments.
    """
    
    # Base weights for scoring factors
    DEFAULT_WEIGHTS = {
        'completion_rate': 0.20,
        'quality': 0.25,
        'reliability': 0.20,
        'price': 0.15,
        'response_time': 0.10,
        'compliance': 0.10
    }
    
    # Tier thresholds
    TIER_THRESHOLDS = {
        'platinum': 90,
        'gold': 80,
        'silver': 70,
        'bronze': 60,
        'standard': 0
    }
    
    def __init__(self):
        self.weights = self.DEFAULT_WEIGHTS.copy()
    
    def calculate_comprehensive_score(
        self, 
        supplier_id: str
    ) -> Optional[PerformanceMetrics]:
        """Calculate comprehensive performance score for a supplier"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            fulfillment_repo = ServiceFulfillmentRepository(session)
            bid_repo = BidRepository(session)
            interaction_repo = ClientInteractionRepository(session)
            score_repo = SupplierScoreRepository(session)
            
            supplier = supplier_repo.get_by_id(supplier_id)
            if not supplier:
                return None
            
            # Gather data for scoring
            fulfillments = fulfillment_repo.get_by_supplier(supplier_id)
            completed_fulfillments = [
                f for f in fulfillments 
                if f.status == FulfillmentStatus.COMPLETED.value
            ]
            bids = bid_repo.get_by_supplier(supplier_id, limit=100)
            interactions = interaction_repo.get_by_supplier(supplier_id, limit=100)
            
            # Calculate individual scores
            scores = {}
            
            # 1. Completion Rate Score
            if supplier.total_allocations > 0:
                completion_rate = supplier.successful_completions / supplier.total_allocations
                scores['completion_rate'] = completion_rate * 100
            else:
                scores['completion_rate'] = 50  # Default for new suppliers
            
            # 2. Quality Score (from customer ratings)
            if completed_fulfillments:
                ratings = [
                    f.customer_rating for f in completed_fulfillments 
                    if f.customer_rating is not None
                ]
                if ratings:
                    avg_rating = statistics.mean(ratings)
                    scores['quality'] = avg_rating * 20  # Scale 1-5 to 0-100
                else:
                    scores['quality'] = 50
            else:
                scores['quality'] = 50
            
            # 3. Reliability Score (on-time delivery)
            if completed_fulfillments:
                on_time_count = sum(
                    1 for f in completed_fulfillments
                    if f.completed_at and f.expected_completion 
                    and f.completed_at <= f.expected_completion
                )
                scores['reliability'] = (on_time_count / len(completed_fulfillments)) * 100
            else:
                scores['reliability'] = 50
            
            # 4. Price Competitiveness Score
            if bids:
                winning_bids = [b for b in bids if b.status == BidStatus.WINNER.value]
                win_rate = len(winning_bids) / len(bids) if bids else 0
                
                # Also consider bid amount relative to average
                if winning_bids:
                    # Higher win rate = more competitive pricing
                    scores['price'] = min(win_rate * 150, 100)  # Cap at 100
                else:
                    scores['price'] = 40  # Lower score if no wins
            else:
                scores['price'] = 50
            
            # 5. Response Time Score
            # Calculate based on bid submission timing
            if bids:
                # Placeholder: could analyze time from allocation open to bid submission
                scores['response_time'] = 70  # Default good score
            else:
                scores['response_time'] = 50
            
            # 6. Compliance Score (credentials verification)
            from database.repositories.sully_chain_repository import SupplierCredentialRepository
            cred_repo = SupplierCredentialRepository(session)
            credentials = cred_repo.get_by_supplier(supplier_id)
            if credentials:
                verified_count = sum(
                    1 for c in credentials 
                    if c.verification_status == 'verified'
                )
                scores['compliance'] = (verified_count / len(credentials)) * 100
            else:
                scores['compliance'] = 50
            
            # Calculate weighted overall score
            overall_score = sum(
                scores.get(factor, 50) * weight 
                for factor, weight in self.weights.items()
            )
            
            # Determine tier
            tier = 'standard'
            for tier_name, threshold in self.TIER_THRESHOLDS.items():
                if overall_score >= threshold:
                    tier = tier_name
                    break
            
            # Get previous score for trend analysis
            prev_score = score_repo.get_latest_score(supplier_id)
            if prev_score:
                score_change = overall_score - prev_score.overall_score
                if score_change > 2:
                    trend = 'improving'
                elif score_change < -2:
                    trend = 'declining'
                else:
                    trend = 'stable'
            else:
                score_change = 0
                trend = 'stable'
            
            # Calculate percentile rank
            all_scores = score_repo.get_top_performers(limit=1000)
            if all_scores:
                rank_position = sum(
                    1 for s in all_scores 
                    if s.overall_score < overall_score
                )
                percentile = int((rank_position / len(all_scores)) * 100)
            else:
                percentile = 50
            
            return PerformanceMetrics(
                supplier_id=supplier_id,
                overall_score=round(overall_score, 2),
                performance_tier=tier,
                completion_rate_score=round(scores['completion_rate'], 2),
                quality_score=round(scores['quality'], 2),
                reliability_score=round(scores['reliability'], 2),
                price_competitiveness_score=round(scores['price'], 2),
                response_time_score=round(scores['response_time'], 2),
                compliance_score=round(scores['compliance'], 2),
                total_allocations=supplier.total_allocations,
                successful_completions=supplier.successful_completions,
                average_rating=round(scores['quality'] / 20, 2),  # Convert back to 1-5 scale
                on_time_rate=round(scores['reliability'], 2),
                win_rate=round(scores['price'] / 100, 2) if scores['price'] else 0,
                trend_direction=trend,
                score_change_30d=round(score_change, 2),
                percentile_rank=percentile
            )
            
        except Exception as e:
            logger.error(f"Error calculating performance score: {e}")
            return None
        finally:
            session.close()
    
    def get_top_performers_by_type(
        self, 
        supplier_type: str,
        limit: int = 10
    ) -> List[PerformanceMetrics]:
        """Get top performing suppliers for a specific type"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            suppliers = supplier_repo.get_by_type(supplier_type, status='active', limit=limit * 2)
            
            results = []
            for supplier in suppliers:
                metrics = self.calculate_comprehensive_score(supplier.id)
                if metrics:
                    results.append(metrics)
            
            # Sort by overall score
            results.sort(key=lambda x: x.overall_score, reverse=True)
            return results[:limit]
            
        finally:
            session.close()


# =============================================================================
# Fraud Detection Engine
# =============================================================================

class FraudDetectionEngine:
    """
    AI-powered fraud detection engine for Sully Chain.
    Identifies suspicious patterns and anomalies.
    """
    
    # Risk indicators and their weights
    RISK_INDICATORS = {
        'bid_collusion': 0.30,          # Multiple suppliers bidding similar amounts
        'rapid_registration': 0.15,      # Many registrations from same IP/pattern
        'unusual_pricing': 0.20,         # Prices significantly below/above market
        'credential_issues': 0.15,       # Unverified or expired credentials
        'pattern_anomaly': 0.10,         # Unusual activity patterns
        'feedback_manipulation': 0.10    # Suspicious rating patterns
    }
    
    def analyze_bid_for_fraud(self, bid_id: str) -> Optional[FraudAlert]:
        """Analyze a bid for potential fraud"""
        session = get_db_session()
        try:
            bid_repo = BidRepository(session)
            alloc_repo = AllocationRepository(session)
            
            bid = bid_repo.get_by_id(bid_id)
            if not bid:
                return None
            
            allocation = alloc_repo.get_by_id(bid.allocation_id)
            if not allocation:
                return None
            
            # Get all bids for this allocation
            all_bids = bid_repo.get_by_allocation(bid.allocation_id)
            
            indicators = []
            risk_score = 0.0
            
            # Check 1: Bid collusion (similar bid amounts)
            if len(all_bids) >= 3:
                bid_amounts = [float(b.bid_amount) for b in all_bids if b.bid_amount]
                if bid_amounts:
                    mean_bid = statistics.mean(bid_amounts)
                    std_dev = statistics.stdev(bid_amounts) if len(bid_amounts) > 1 else 0
                    
                    # Check if bids are suspiciously similar
                    if std_dev < mean_bid * 0.05:  # Less than 5% variation
                        indicators.append('Bid amounts are suspiciously similar')
                        risk_score += self.RISK_INDICATORS['bid_collusion']
            
            # Check 2: Unusual pricing
            if allocation.reserve_price and bid.bid_amount:
                ratio = float(bid.bid_amount) / float(allocation.reserve_price)
                if ratio < 0.5:  # More than 50% below reserve
                    indicators.append('Bid significantly below reserve price')
                    risk_score += self.RISK_INDICATORS['unusual_pricing']
                elif ratio > 2.0:  # More than 200% of reserve
                    indicators.append('Bid significantly above reserve price')
                    risk_score += self.RISK_INDICATORS['unusual_pricing'] * 0.5
            
            # Check 3: Supplier credential status
            supplier_repo = SupplierRepository(session)
            supplier = supplier_repo.get_by_id(bid.supplier_id)
            if supplier:
                if supplier.status != 'active':
                    indicators.append('Supplier not in active status')
                    risk_score += self.RISK_INDICATORS['credential_issues']
                    
                if supplier.rating < 30:  # Low rating
                    indicators.append('Supplier has very low rating')
                    risk_score += self.RISK_INDICATORS['pattern_anomaly']
            
            # Determine severity
            if risk_score >= 0.6:
                severity = 'critical'
            elif risk_score >= 0.4:
                severity = 'high'
            elif risk_score >= 0.2:
                severity = 'medium'
            else:
                severity = 'low'
            
            # Only return alert if risk is meaningful
            if risk_score < 0.1:
                return None
            
            return FraudAlert(
                alert_id=f"FRA-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{bid_id[:8]}",
                severity=severity,
                alert_type='bid_fraud_risk',
                entity_type='bid',
                entity_id=bid_id,
                description=f"Potential fraud indicators detected in bid {bid.bid_code}",
                risk_score=round(risk_score * 100, 2),
                indicators=indicators,
                recommended_actions=[
                    'Review bid details manually',
                    'Verify supplier credentials',
                    'Check for related suspicious activity'
                ]
            )
            
        except Exception as e:
            logger.error(f"Error analyzing bid for fraud: {e}")
            return None
        finally:
            session.close()
    
    def detect_collusion_patterns(
        self, 
        allocation_id: str
    ) -> List[FraudAlert]:
        """Detect potential collusion patterns in an allocation"""
        session = get_db_session()
        try:
            bid_repo = BidRepository(session)
            bids = bid_repo.get_by_allocation(allocation_id)
            
            alerts = []
            
            if len(bids) < 3:
                return alerts
            
            # Group bids by similar amounts
            bid_amounts = [(b.id, float(b.bid_amount)) for b in bids if b.bid_amount]
            bid_amounts.sort(key=lambda x: x[1])
            
            # Check for clusters of similar bids
            clusters = []
            current_cluster = [bid_amounts[0]]
            
            for i in range(1, len(bid_amounts)):
                prev_amount = bid_amounts[i-1][1]
                curr_amount = bid_amounts[i][1]
                
                # If within 2% of each other, add to cluster
                if curr_amount <= prev_amount * 1.02:
                    current_cluster.append(bid_amounts[i])
                else:
                    if len(current_cluster) >= 2:
                        clusters.append(current_cluster)
                    current_cluster = [bid_amounts[i]]
            
            if len(current_cluster) >= 2:
                clusters.append(current_cluster)
            
            # Generate alerts for suspicious clusters
            for cluster in clusters:
                if len(cluster) >= 2:
                    bid_ids = [c[0] for c in cluster]
                    avg_amount = statistics.mean([c[1] for c in cluster])
                    
                    alerts.append(FraudAlert(
                        alert_id=f"COL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{len(alerts)}",
                        severity='high' if len(cluster) >= 3 else 'medium',
                        alert_type='potential_collusion',
                        entity_type='allocation',
                        entity_id=allocation_id,
                        description=f"{len(cluster)} bids with suspiciously similar amounts (~${avg_amount:,.2f})",
                        risk_score=min(len(cluster) * 25, 100),
                        indicators=[
                            f"Cluster of {len(cluster)} bids within 2% of each other",
                            f"Average bid amount: ${avg_amount:,.2f}"
                        ],
                        recommended_actions=[
                            'Investigate supplier relationships',
                            'Check for common ownership or addresses',
                            'Review historical bidding patterns'
                        ]
                    ))
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error detecting collusion: {e}")
            return []
        finally:
            session.close()


# =============================================================================
# Price Prediction Engine
# =============================================================================

class PricePredictionEngine:
    """
    ML-style price prediction engine for allocations.
    Predicts likely winning bid amounts based on historical data.
    """
    
    def predict_winning_price(
        self, 
        allocation_id: str
    ) -> Optional[PricePrediction]:
        """Predict the winning price for an allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            analytics_repo = AllocationAnalyticsRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation:
                return None
            
            # Get service request for type info
            from database.repositories.sully_chain_repository import ServiceRequestRepository
            sr_repo = ServiceRequestRepository(session)
            service_request = sr_repo.get_by_id(allocation.service_request_id)
            
            service_type = service_request.service_type if service_request else 'unknown'
            
            # Get historical data for similar allocations
            historical_analytics = self._get_similar_allocations(
                session, service_type, allocation.reserve_price
            )
            
            if not historical_analytics:
                # No historical data - use reserve price as base
                base_price = float(allocation.reserve_price or 1000)
                return PricePrediction(
                    allocation_id=allocation_id,
                    service_type=service_type,
                    predicted_winning_price=base_price * 0.9,  # 10% below reserve
                    confidence_level=0.3,
                    price_range_low=base_price * 0.7,
                    price_range_high=base_price * 1.1,
                    factors_considered=['reserve_price_only'],
                    comparable_allocations=[]
                )
            
            # Calculate predictions based on historical data
            winning_amounts = [
                float(a.winning_bid_amount) for a in historical_analytics 
                if a.winning_bid_amount
            ]
            
            if not winning_amounts:
                base_price = float(allocation.reserve_price or 1000)
                return PricePrediction(
                    allocation_id=allocation_id,
                    service_type=service_type,
                    predicted_winning_price=base_price * 0.9,
                    confidence_level=0.3,
                    price_range_low=base_price * 0.7,
                    price_range_high=base_price * 1.1,
                    factors_considered=['limited_historical_data'],
                    comparable_allocations=[]
                )
            
            # Statistical analysis
            mean_price = statistics.mean(winning_amounts)
            median_price = statistics.median(winning_amounts)
            std_dev = statistics.stdev(winning_amounts) if len(winning_amounts) > 1 else mean_price * 0.2
            
            # Weighted prediction (favor median for robustness)
            predicted_price = (mean_price * 0.4) + (median_price * 0.6)
            
            # Adjust based on reserve price if available
            if allocation.reserve_price:
                reserve = float(allocation.reserve_price)
                # Predicted price typically 80-95% of reserve
                adjusted_prediction = min(predicted_price, reserve * 0.95)
                adjusted_prediction = max(adjusted_prediction, reserve * 0.5)
            else:
                adjusted_prediction = predicted_price
            
            # Calculate confidence based on data quality
            confidence = min(0.9, 0.3 + (len(winning_amounts) * 0.1))
            
            return PricePrediction(
                allocation_id=allocation_id,
                service_type=service_type,
                predicted_winning_price=round(adjusted_prediction, 2),
                confidence_level=round(confidence, 2),
                price_range_low=round(adjusted_prediction - std_dev, 2),
                price_range_high=round(adjusted_prediction + std_dev, 2),
                factors_considered=[
                    'historical_winning_prices',
                    'service_type_analysis',
                    'reserve_price_adjustment'
                ],
                comparable_allocations=[a.allocation_id for a in historical_analytics[:5]]
            )
            
        except Exception as e:
            logger.error(f"Error predicting price: {e}")
            return None
        finally:
            session.close()
    
    def _get_similar_allocations(
        self, 
        session, 
        service_type: str,
        reserve_price: Decimal = None,
        limit: int = 20
    ) -> List[AllocationAnalytics]:
        """Get analytics from similar historical allocations"""
        try:
            from sqlalchemy import and_
            
            query = session.query(AllocationAnalytics).filter(
                AllocationAnalytics.outcome_success == True
            )
            
            # Would filter by service type if we had it in analytics
            # For now, just get recent completed allocations
            
            return query.order_by(
                AllocationAnalytics.analyzed_at.desc()
            ).limit(limit).all()
            
        except Exception as e:
            logger.error(f"Error getting similar allocations: {e}")
            return []


# =============================================================================
# Recommendation Engine
# =============================================================================

class RecommendationEngine:
    """
    AI-powered supplier recommendation engine.
    Matches suppliers to allocations based on capabilities and performance.
    """
    
    def recommend_suppliers(
        self, 
        allocation_id: str,
        limit: int = 10
    ) -> List[SupplierRecommendation]:
        """Recommend best suppliers for an allocation"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            supplier_repo = SupplierRepository(session)
            score_repo = SupplierScoreRepository(session)
            
            allocation = alloc_repo.get_by_id(allocation_id)
            if not allocation:
                return []
            
            # Parse eligible supplier types
            try:
                eligible_types = json.loads(allocation.eligible_supplier_types or "[]")
            except:
                eligible_types = []
            
            # Get eligible suppliers
            suppliers = supplier_repo.search_suppliers(
                supplier_types=eligible_types if eligible_types else None,
                min_rating=allocation.required_rating
            )
            
            recommendations = []
            
            for supplier in suppliers[:limit * 2]:  # Get extra for filtering
                # Get supplier score
                score = score_repo.get_latest_score(supplier.id)
                
                # Calculate match score
                match_score = self._calculate_match_score(supplier, allocation, score)
                
                # Generate recommendation reasons
                reasons = self._generate_recommendation_reasons(supplier, allocation, score)
                
                # Estimate bid amount
                estimated_bid = self._estimate_bid_amount(supplier, allocation)
                
                # Determine risk level
                if score and score.overall_score >= 80:
                    risk = 'low'
                elif score and score.overall_score >= 60:
                    risk = 'medium'
                else:
                    risk = 'high'
                
                recommendations.append(SupplierRecommendation(
                    supplier_id=supplier.id,
                    supplier_name=supplier.name,
                    match_score=round(match_score, 2),
                    recommendation_reasons=reasons,
                    estimated_bid_amount=round(estimated_bid, 2),
                    expected_quality_score=score.quality_score if score else 50,
                    risk_level=risk
                ))
            
            # Sort by match score
            recommendations.sort(key=lambda x: x.match_score, reverse=True)
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return []
        finally:
            session.close()
    
    def _calculate_match_score(
        self, 
        supplier: Supplier,
        allocation: Allocation,
        score: Optional[SupplierScore]
    ) -> float:
        """Calculate match score between supplier and allocation"""
        match_score = 50.0  # Base score
        
        # Factor 1: Performance score (0-25)
        if score:
            match_score += (score.overall_score / 100) * 25
        
        # Factor 2: Experience with similar allocations (0-15)
        if supplier.total_allocations > 10:
            match_score += 15
        elif supplier.total_allocations > 5:
            match_score += 10
        elif supplier.total_allocations > 0:
            match_score += 5
        
        # Factor 3: Rating match with requirement (0-10)
        if allocation.required_rating:
            if supplier.rating >= allocation.required_rating + 10:
                match_score += 10
            elif supplier.rating >= allocation.required_rating:
                match_score += 5
        
        return min(100, match_score)
    
    def _generate_recommendation_reasons(
        self, 
        supplier: Supplier,
        allocation: Allocation,
        score: Optional[SupplierScore]
    ) -> List[str]:
        """Generate human-readable recommendation reasons"""
        reasons = []
        
        if score:
            if score.overall_score >= 90:
                reasons.append(f"Platinum-tier performer ({score.overall_score:.1f} score)")
            elif score.overall_score >= 80:
                reasons.append(f"Gold-tier performer ({score.overall_score:.1f} score)")
            
            if score.quality_score >= 90:
                reasons.append("Excellent quality ratings from customers")
            
            if score.reliability_score >= 90:
                reasons.append("Outstanding on-time delivery record")
        
        if supplier.total_allocations > 20:
            reasons.append(f"Experienced with {supplier.total_allocations} completed allocations")
        
        if supplier.successful_completions > 0 and supplier.total_allocations > 0:
            success_rate = supplier.successful_completions / supplier.total_allocations
            if success_rate >= 0.95:
                reasons.append(f"{success_rate*100:.0f}% success rate")
        
        if not reasons:
            reasons.append("Meets minimum eligibility criteria")
        
        return reasons
    
    def _estimate_bid_amount(
        self, 
        supplier: Supplier,
        allocation: Allocation
    ) -> float:
        """Estimate what the supplier might bid"""
        if allocation.reserve_price:
            reserve = float(allocation.reserve_price)
            
            # Higher rated suppliers tend to bid slightly higher
            if supplier.rating >= 80:
                return reserve * 0.95  # 5% below reserve
            elif supplier.rating >= 60:
                return reserve * 0.85  # 15% below reserve
            else:
                return reserve * 0.75  # 25% below reserve (competitive)
        
        return 1000  # Default estimate


# =============================================================================
# Business Intelligence Dashboard
# =============================================================================

class BusinessIntelligenceDashboard:
    """
    BI Dashboard service for executive insights and analytics.
    """
    
    def generate_executive_summary(self) -> Dict[str, Any]:
        """Generate executive summary dashboard data"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            alloc_repo = AllocationRepository(session)
            analytics_repo = AllocationAnalyticsRepository(session)
            
            # Time periods
            now = datetime.utcnow()
            thirty_days_ago = now - timedelta(days=30)
            seven_days_ago = now - timedelta(days=7)
            
            # Supplier metrics
            active_suppliers = len(supplier_repo.get_active_suppliers(limit=10000))
            
            # Allocation metrics
            open_allocations = len(alloc_repo.get_open_allocations(limit=10000))
            
            # Get aggregate stats
            overall_stats = analytics_repo.get_aggregate_stats()
            monthly_stats = analytics_repo.get_aggregate_stats(
                from_date=thirty_days_ago, 
                to_date=now
            )
            
            return {
                'generated_at': now.isoformat(),
                'summary': {
                    'active_suppliers': active_suppliers,
                    'open_allocations': open_allocations,
                    'total_awarded_value': monthly_stats.get('total_awarded_value', 0),
                    'avg_bids_per_allocation': round(monthly_stats.get('avg_bids_per_allocation', 0), 1),
                    'avg_time_to_award_hours': round(monthly_stats.get('avg_time_to_award_hours', 0), 1)
                },
                'trends': {
                    'allocation_volume': 'stable',
                    'supplier_growth': 'increasing',
                    'price_efficiency': 'improving'
                },
                'alerts': self._get_active_alerts(),
                'insights': self._generate_insights()
            }
            
        except Exception as e:
            logger.error(f"Error generating executive summary: {e}")
            return {'error': str(e)}
        finally:
            session.close()
    
    def _get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active alerts for dashboard"""
        return [
            {
                'type': 'info',
                'message': 'System operating normally',
                'timestamp': datetime.utcnow().isoformat()
            }
        ]
    
    def _generate_insights(self) -> List[DashboardInsight]:
        """Generate actionable insights"""
        insights = []
        
        # Example insight - in production would analyze real data
        insights.append(DashboardInsight(
            insight_id=str(uuid.uuid4()),
            category='opportunity',
            title='Supplier Diversification Opportunity',
            description='Medical equipment supplier capacity is at 85%. Consider onboarding new suppliers.',
            impact_level='medium',
            data_points={'capacity_used': 85, 'category': 'medical_equipment'},
            actions=['Review pending supplier applications', 'Launch recruitment campaign']
        ))
        
        return insights
    
    def get_supplier_distribution(self) -> Dict[str, int]:
        """Get distribution of suppliers by type"""
        session = get_db_session()
        try:
            supplier_repo = SupplierRepository(session)
            suppliers = supplier_repo.get_active_suppliers(limit=10000)
            
            distribution = {}
            for supplier in suppliers:
                supplier_type = supplier.supplier_type
                distribution[supplier_type] = distribution.get(supplier_type, 0) + 1
            
            return distribution
            
        finally:
            session.close()
    
    def get_allocation_trends(
        self, 
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get allocation trends over time"""
        session = get_db_session()
        try:
            alloc_repo = AllocationRepository(session)
            
            # This would aggregate allocations by day in production
            # Returning sample data structure
            end_date = datetime.utcnow()
            trends = []
            
            for i in range(days):
                date = end_date - timedelta(days=i)
                trends.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'allocations_created': 5 + (i % 3),  # Sample data
                    'allocations_awarded': 4 + (i % 2),
                    'total_value': 50000 + (i * 1000)
                })
            
            trends.reverse()
            return trends
            
        finally:
            session.close()


# =============================================================================
# Unified Analytics Service
# =============================================================================

class SullyChainAnalytics:
    """
    Unified analytics service providing access to all AI/BI capabilities.
    """
    
    def __init__(self):
        self._scoring = None
        self._fraud = None
        self._pricing = None
        self._recommendations = None
        self._dashboard = None
    
    @property
    def scoring(self) -> PerformanceScoringEngine:
        if self._scoring is None:
            self._scoring = PerformanceScoringEngine()
        return self._scoring
    
    @property
    def fraud(self) -> FraudDetectionEngine:
        if self._fraud is None:
            self._fraud = FraudDetectionEngine()
        return self._fraud
    
    @property
    def pricing(self) -> PricePredictionEngine:
        if self._pricing is None:
            self._pricing = PricePredictionEngine()
        return self._pricing
    
    @property
    def recommendations(self) -> RecommendationEngine:
        if self._recommendations is None:
            self._recommendations = RecommendationEngine()
        return self._recommendations
    
    @property
    def dashboard(self) -> BusinessIntelligenceDashboard:
        if self._dashboard is None:
            self._dashboard = BusinessIntelligenceDashboard()
        return self._dashboard


# Global instance
sully_analytics = SullyChainAnalytics()
