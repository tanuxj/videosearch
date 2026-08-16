/**
 * Legal identity constants used by the Terms of Service and Privacy Policy.
 *
 * ⚠ UPDATE BEFORE SHIPPING — the values below are placeholders:
 *   • LEGAL_OPERATOR          → your legal entity name ("Acme, Inc.")
 *   • LEGAL_CONTACT_EMAIL     → the inbox your users can actually reach
 *   • LEGAL_GRIEVANCE_OFFICER → the officer's name for Indian users
 *                               (required by India's DPDP Act / IT Rules)
 *
 * Governing law is India (the operator is India-based). Have a lawyer review
 * both documents before you rely on them — nothing in this file is legal
 * advice.
 */

/** The legal entity that operates the service. */
export const LEGAL_OPERATOR = 'SearchInVideo'

/** The support / privacy inbox shown throughout the documents. */
export const LEGAL_CONTACT_EMAIL = 'support@your-company.com'

/**
 * Governing law for the Terms, and where the operator is established.
 * Disputes go to the courts at the operator's registered office in India.
 */
export const LEGAL_JURISDICTION = 'India'

/**
 * Grievance redressal officer for Indian users (DPDP Act 2023 / IT Rules).
 * ⚠ Update the name before shipping.
 */
export const LEGAL_GRIEVANCE_OFFICER = {
  name: 'Grievance Officer',
  email: LEGAL_CONTACT_EMAIL,
}
