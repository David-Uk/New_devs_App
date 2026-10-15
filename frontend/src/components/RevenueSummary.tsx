import React, { useEffect, useState } from 'react';
import { SecureAPI } from '../lib/secureApi';

interface RevenueData {
    property_id: string;
    // FIX (FINDINGS.md 1.4): exact decimal string from the API (e.g. "2250.000").
    // Money must never travel as a JS number - IEEE-754 doubles drift by a cent
    // on NUMERIC(10,3) sub-cent values.
    total_revenue: string;
    currency: string;
    reservations_count: number;
}

// FIX (FINDINGS.md 1.4): format an exact decimal money string for display using
// string/integer math only - no IEEE-754 floats anywhere. The old
// `Math.round(data.total_revenue * 100) / 100` multiplied the double first, so
// values like 2249.999 could land at 2249.99 (a cent off) depending on binary
// representation. Rounds half-up on the sub-cent digit, then groups thousands.
function formatMoneyExact(exact: string): { display: string; hasSubCentPrecision: boolean } {
    const trimmed = String(exact).trim();
    const negative = trimmed.startsWith('-');
    const body = negative ? trimmed.slice(1) : trimmed;
    const [intDigits = '0', fracDigits = ''] = body.split('.');
    const intPart = intDigits.replace(/\D/g, '') || '0';
    const firstTwo = (fracDigits + '00').slice(0, 2);
    const remainder = fracDigits.slice(2);

    // Round half-up using integer operations only (never float multiply/round).
    let cents = Number(intPart) * 100 + Number(firstTwo);
    if (remainder.length > 0 && remainder[0] >= '5') {
        cents += 1;
    }
    const dollars = Math.floor(cents / 100);
    const centsPart = String(cents % 100).padStart(2, '0');
    const display = `${negative ? '-' : ''}${dollars.toLocaleString('en-US')}.${centsPart}`;

    // Any non-zero digit beyond the cent = sub-cent precision the display rounds away.
    const hasSubCentPrecision = /[1-9]/.test(remainder);
    return { display, hasSubCentPrecision };
}

interface RevenueSummaryProps {
    propertyId?: string;
    debugTenant?: string; 
    showRaw?: boolean;
}

export const RevenueSummary: React.FC<RevenueSummaryProps> = ({ propertyId = 'prop-001', debugTenant, showRaw }) => {
    const [data, setData] = useState<RevenueData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const activeTenant = debugTenant || 'candidate';

    useEffect(() => {
        const fetchRevenue = async () => {
            setLoading(true);
            try {
                // Use SecureAPI to handle authentication automatically
                // We pass the simulatedTenant option which SecureAPI will attach as a header
                const response = await SecureAPI.getDashboardSummary(propertyId, {
                    simulatedTenant: activeTenant,
                    timestamp: Date.now()
                });
                setData(response);
            } catch (err) {
                setError('Failed to load revenue data');
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        fetchRevenue();
    }, [propertyId, activeTenant]);

    if (loading) {
        return (
            <div className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
                <div className="animate-pulse space-y-4">
                    <div className="h-4 bg-gray-100 rounded w-1/4"></div>
                    <div className="h-8 bg-gray-100 rounded w-1/2"></div>
                    <div className="flex gap-4 pt-4">
                        <div className="h-12 bg-gray-100 rounded flex-1"></div>
                        <div className="h-12 bg-gray-100 rounded flex-1"></div>
                    </div>
                </div>
            </div>
        );
    }

    if (error) return <div className="p-4 text-red-500 bg-red-50 rounded-lg">{error}</div>;
    if (!data) return null;

    // FIX (FINDINGS.md 1.4): exact string-based rounding (integer math), replacing
    // `Math.round(data.total_revenue * 100) / 100` float arithmetic.
    const { display: displayTotal, hasSubCentPrecision } = formatMoneyExact(String(data.total_revenue));

    return (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden hover:shadow-md transition-shadow duration-300">
            {showRaw && (
                <div className="p-3 bg-gray-50 text-xs font-mono border-b border-gray-100 overflow-auto max-h-32">
                    <strong className="block mb-1 text-gray-500 uppercase tracking-wider text-[10px]">Raw API Response</strong>
                    <pre className="text-gray-700">{JSON.stringify(data, null, 2)}</pre>
                </div>
            )}

            <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide">Total Revenue</h2>
                        <div className="flex items-baseline gap-2 mt-1">
                            <span className="text-3xl font-bold text-gray-900 tracking-tight">
                                {data.currency} {displayTotal}
                            </span>
                            {/* Fake trend indicator for premium feel */}
                            <span className="inline-flex items-baseline px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 md:mt-2 lg:mt-0">
                                <svg className="-ml-1 mr-0.5 h-3 w-3 flex-shrink-0 self-center text-green-500" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                                    <path fillRule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
                                </svg>
                                12%
                            </span>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-100">
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Property ID</p>
                        <p className="text-sm font-semibold text-gray-700 font-mono mt-1">{data.property_id}</p>
                    </div>
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Reservations</p>
                        <p className="text-sm font-semibold text-gray-700 mt-1">{data.reservations_count} <span className="font-normal text-gray-400">bookings</span></p>
                    </div>
                </div>

                {/* Precision Warning Area */}
                <div className="mt-4 h-6">
                    {/* FIX (FINDINGS.md 1.4): string-based sub-cent detection replaces
                        `Math.abs(data.total_revenue - displayTotal) > 0.000001` float compare */}
                    {hasSubCentPrecision && showRaw && (
                        <div className="flex items-center text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded">
                            <svg className="h-4 w-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                            </svg>
                            Precision Mismatch Detected
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
