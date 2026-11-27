from __future__ import annotations

from typing import Any

from app.agent.verifier import ResolutionOption, ResolutionPlan


def _amount_phrase(difference_ref: str | None) -> str:
    if difference_ref:
        return f"{{difference:{difference_ref}}}"
    return "the recorded discrepancy"


def build_resolution_plan(
    exception_type: str | None,
    *,
    difference_ref: str | None = None,
    has_candidate_payments: bool = False,
    has_duplicates: bool = False,
    record_context: dict[str, Any] | None = None,
) -> ResolutionPlan:
    """Build a grounded, evidence-safe 8-part resolution plan without inventing records or facts."""
    _ = record_context
    diff = _amount_phrase(difference_ref)

    if exception_type == "PARTIAL_PAYMENT":
        solutions = [
            ResolutionOption(
                id="partial_payment",
                title="Partial Payment",
                possible_cause="The vendor may have received only part of the invoice amount in this installment.",
                action="Check payment history and bank feeds for an additional payment covering the remaining balance.",
                resolution="If another valid payment exists, import or link it to the invoice and re-run matching to reconcile the full total.",
                workflow_action="request_info",
            ),
            ResolutionOption(
                id="outstanding_balance",
                title="Outstanding Payment",
                possible_cause=f"The remaining balance of {diff} may not have been paid yet.",
                action="Verify the unpaid balance against open payment schedules and the vendor statement.",
                resolution="Keep the invoice partially unpaid as an open balance until the remaining payment is confirmed and recorded.",
                workflow_action="request_info",
            ),
            ResolutionOption(
                id="incorrect_payment_record",
                title="Incorrect Payment Record",
                possible_cause="The imported payment record may contain an entry or extraction error in its amount.",
                action="Verify the bank statement, payment receipt, and transaction reference against the recorded payment.",
                resolution="Correct the payment record only after obtaining verified bank evidence and proper authorization.",
                workflow_action="escalate",
            ),
            ResolutionOption(
                id="credit_note_adjustment",
                title="Invoice Adjustment or Credit Note",
                possible_cause=f"The vendor may have issued a credit note or approved adjustment of {diff}.",
                action="Check vendor correspondence and credit memos for an authorized credit note matching the difference.",
                resolution="Submit the verified adjustment proposal through the existing approval workflow once supporting documentation is attached.",
                workflow_action="propose_adjustment",
            ),
        ]
        if has_candidate_payments:
            recommended_id: str | None = "partial_payment"
            recommended_text = (
                "Other payments were returned for this vendor. First check whether an additional payment explains "
                f"the remaining {diff} before proposing an adjustment. No single cause is confirmed until bank evidence is verified."
            )
            confidence: str = "medium"
            confidence_rationale = "Linked invoice and payment amounts are verified, and other vendor payments exist to inspect."
            insufficient = False
        else:
            recommended_id = "credit_note_adjustment"
            recommended_text = (
                f"Persisted records show a verified difference of {diff} with no additional unlinked payment found. "
                "Verify the bank statement and vendor statement first; if confirmed as a credit note or write-off, submit the adjustment for approval, "
                "or retain the balance as outstanding if payment is still pending."
            )
            confidence = "medium"
            confidence_rationale = (
                "The numeric gap is verified from persisted records, but external evidence (bank statement or credit note) is required to confirm the root cause."
            )
            insufficient = False

        return ResolutionPlan(
            problem_identification=f"The linked payment amount is lower than the invoice amount by {diff}.",
            possible_causes=[
                "The payment may be an initial installment of a split or partial payment.",
                f"The remaining {diff} may still be unpaid and outstanding.",
                "The recorded payment amount may contain a data entry or import discrepancy.",
                f"A vendor credit note, withholding, or price adjustment of {diff} may apply.",
            ],
            possible_solutions=solutions,
            recommended_solution_id=recommended_id,
            recommended_solution=recommended_text,
            required_actions=[
                "Review payment history for the vendor to check for additional or split payments.",
                "Verify the settled payment amount against the bank statement and remittance advice.",
                "Confirm with the vendor whether a credit note applies or whether the balance remains payable.",
                "Select the appropriate resolution path and submit any financial adjustment through the approval workflow.",
            ],
            required_documents=[
                "Bank statement or payment settlement confirmation",
                "Payment receipt / remittance advice",
                "Vendor statement of account or approved credit note (if claiming an adjustment)",
            ],
            expected_outcome=(
                "No financial records are modified automatically. Once the analyst submits a selected path and an authorized approver signs off, "
                "either an approved adjustment resolves the exception or the invoice remains tracked until the remaining payment arrives."
            ),
            confidence_level=confidence,  # type: ignore[arg-type]
            confidence_rationale=confidence_rationale,
            insufficient_evidence=insufficient,
        )

    if exception_type == "OVERPAYMENT":
        return ResolutionPlan(
            problem_identification=f"The linked payment exceeds the invoice amount (difference: {diff}).",
            possible_causes=[
                "The vendor may have been overpaid due to a payment entry or remittance mistake.",
                "A single payment may have bundled this invoice together with another open invoice.",
                "The invoice record may be missing an approved charge, tax, or debit adjustment.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="vendor_refund_or_credit",
                    title="Request Vendor Refund or Credit Memo",
                    possible_cause="The payment may genuinely exceed the agreed invoice total.",
                    action="Verify the bank settlement and contact the vendor to confirm the overpayment.",
                    resolution="Submit an adjustment proposal for approval and track the vendor refund or credit memo against future invoices.",
                    workflow_action="propose_adjustment",
                ),
                ResolutionOption(
                    id="bundled_multi_invoice_payment",
                    title="Check for Multi-Invoice Remittance",
                    possible_cause="The excess amount may cover another open invoice from the same vendor.",
                    action="Review open invoices for the same vendor and inspect the remittance breakdown.",
                    resolution="Allocate the verified payment breakdown across the matching invoices only after confirming remittance evidence.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="incorrect_payment_or_invoice_entry",
                    title="Verify Payment and Invoice Records",
                    possible_cause="Either the imported payment amount or invoice total may be misstated.",
                    action="Compare the original PDF invoice and bank debit against the persisted records.",
                    resolution="Escalate for authorized correction only after verified source documents confirm an entry error.",
                    workflow_action="escalate",
                ),
            ],
            recommended_solution_id="vendor_refund_or_credit",
            recommended_solution=(
                "Verify the bank debit and remittance breakdown first. If no other open invoice accounts for the excess, "
                "request a vendor credit memo or refund and submit the adjustment for approval."
            ),
            required_actions=[
                "Confirm the exact debited amount on the bank statement.",
                "Check the vendor's open invoices and remittance advice for bundled payments.",
                "Request written confirmation or a credit memo from the vendor before proposing an adjustment.",
            ],
            required_documents=[
                "Bank statement showing the settled debit",
                "Remittance advice / payment breakdown",
                "Original vendor invoice and any vendor credit memo",
            ],
            expected_outcome=(
                "No records are changed automatically. Submitting the selected resolution routes any adjustment for approver review "
                "and preserves the full audit trail."
            ),
            confidence_level="medium",
            confidence_rationale="The overpayment gap is verified from persisted records, while remittance allocation requires external confirmation.",
            insufficient_evidence=False,
        )

    if exception_type in {"DUPLICATE_INVOICE", "DUPLICATE_PAYMENT"}:
        is_invoice = exception_type == "DUPLICATE_INVOICE"
        noun = "invoice" if is_invoice else "payment"
        return ResolutionPlan(
            problem_identification=(
                f"Two persisted {noun} records appear to share identical identifying details (vendor, reference/number, amount, and date)."
            ),
            possible_causes=[
                f"The same {noun} may have been uploaded or imported twice.",
                f"The vendor or payment channel may have issued two separate {noun}s with identical amounts on the same date.",
                "A re-submitted file may have duplicated an existing entry under a new internal ID.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="confirm_duplicate_upload",
                    title=f"Confirm Duplicate {noun.title()} Upload",
                    possible_cause=f"Both records may represent the exact same source {noun} uploaded twice.",
                    action=f"Compare source files, upload timestamps, and the original vendor {noun} document.",
                    resolution=f"Mark the duplicate {noun} appropriately and route the adjustment through approval without deleting original audit history.",
                    workflow_action="mark_duplicate",
                ),
                ResolutionOption(
                    id="verify_distinct_transactions",
                    title=f"Verify Separate Legitimate {noun.title()}s",
                    possible_cause="Both records may correspond to two distinct, legitimate business transactions.",
                    action="Check purchase orders, delivery receipts, bank references, and vendor confirmation for distinct goods or services.",
                    resolution="Escalate with verified proof of separate deliveries or settlements so the duplicate flag can be overridden safely.",
                    workflow_action="escalate",
                ),
                ResolutionOption(
                    id="vendor_duplicate_billing",
                    title="Request Vendor Cancellation or Credit Note" if is_invoice else "Request Refund for Double Payment",
                    possible_cause=(
                        "The vendor may have accidentally billed the same order twice."
                        if is_invoice
                        else "Two actual bank transfers may have been executed for the same invoice."
                    ),
                    action="Confirm with the vendor and check bank settlement records.",
                    resolution="Obtain written cancellation/credit note or refund confirmation before submitting a resolution proposal for approval.",
                    workflow_action="propose_adjustment",
                ),
            ],
            recommended_solution_id="confirm_duplicate_upload" if has_duplicates else None,
            recommended_solution=(
                f"Duplicate search matched identical persisted {noun} attributes. Verify against the original source document "
                f"and mark the duplicate without deleting audit history—or escalate if two distinct transactions are proven."
                if has_duplicates
                else f"Inspect both {noun} records against original vendor and bank documents before deciding whether to mark as duplicate."
            ),
            required_actions=[
                f"Inspect the original source file and vendor/bank documentation for both {noun} records.",
                "Verify whether any funds were disbursed more than once.",
                "Select the verified resolution and submit it through the approval workflow without deleting audit entries.",
            ],
            required_documents=[
                f"Original vendor {noun} document or bank confirmation",
                "Source import batch / upload reference",
                "Goods receipt or PO confirmation if claiming two separate legitimate transactions",
            ],
            expected_outcome=(
                "The duplicate exception is resolved only after analyst selection and human approval, keeping the original audit log intact."
            ),
            confidence_level="high" if has_duplicates else "medium",
            confidence_rationale=(
                f"Exact duplicate attributes were verified across persisted {noun} records, though source-document review is still required before final action."
                if has_duplicates
                else "Potential duplication requires source document confirmation."
            ),
            insufficient_evidence=not has_duplicates,
        )

    if exception_type == "MISSING_PAYMENT":
        return ResolutionPlan(
            problem_identification="A persisted invoice exists, but no corresponding payment record was found in the database.",
            possible_causes=[
                "The payment may have been executed via bank transfer but not yet imported into Reconcilr.",
                "The payment may exist under a different transaction reference, vendor name, or date outside matching rules.",
                "The invoice may still be genuinely unpaid and awaiting settlement.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="import_missing_payment",
                    title="Check Unimported Bank / ERP Payments",
                    possible_cause="The payment may have been settled externally but omitted from imported payment files.",
                    action="Check recent bank statements and ERP payment batches for a matching disbursement.",
                    resolution="If a verified payment exists, import the payment record through /app/import and re-run matching.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="search_alternate_reference",
                    title="Search by Transaction Reference or Vendor Details",
                    possible_cause="A payment may have been recorded under a different reference format or vendor alias.",
                    action="Search payment records by vendor details, date range, and amount, and request remittance advice.",
                    resolution="Verify the transaction reference and bank evidence before linking or reconciling any candidate payment.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="retain_outstanding",
                    title="Retain Invoice as Outstanding",
                    possible_cause="Payment may genuinely not have occurred yet.",
                    action="Confirm payment due date and treasury payout status with accounts payable.",
                    resolution="Keep the invoice open and outstanding rather than marking it reconciled or inventing a payment.",
                    workflow_action="no_action",
                ),
            ],
            recommended_solution_id=None,
            recommended_solution=(
                "No reliable resolution can be confirmed from persisted records alone because no payment record exists. "
                "Check unimported bank feeds and request payment evidence; if unpaid, retain the invoice as outstanding."
            ),
            required_actions=[
                "Check bank statements and ERP payout exports to verify whether payment has been made.",
                "Request missing payment evidence or remittance advice from treasury/accounts payable.",
                "Do not mark the invoice reconciled until a real payment record is verified and imported.",
            ],
            required_documents=[
                "Bank statement or wire transfer confirmation",
                "Remittance advice or ERP payment batch export",
                "Accounts payable aging / payment schedule confirmation",
            ],
            expected_outcome=(
                "The exception remains unresolved until real payment evidence is imported or accounts payable confirms the invoice should remain open."
            ),
            confidence_level="low",
            confidence_rationale="No payment record was returned by any tool; available evidence cannot distinguish unimported payment from unpaid invoice.",
            insufficient_evidence=True,
        )

    if exception_type == "MISSING_PO":
        return ResolutionPlan(
            problem_identification="An invoice was recorded without a matching purchase order in persisted records.",
            possible_causes=[
                "The purchase order may exist in the procurement system but was not imported.",
                "The vendor may have omitted or misprinted the PO reference on the invoice.",
                "The invoice may relate to an approved non-PO expense or an unauthorized purchase.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="import_missing_po",
                    title="Locate and Import Missing Purchase Order",
                    possible_cause="The PO may exist in procurement records but has not been imported yet.",
                    action="Search the procurement/ERP system by vendor, amount, and order date.",
                    resolution="Import the verified PO record via /app/import and re-run matching.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="verify_vendor_po_reference",
                    title="Request PO Reference from Vendor or Requester",
                    possible_cause="The invoice may omit or mistype the PO number.",
                    action="Confirm the PO reference with the internal requester and vendor invoice copy.",
                    resolution="Obtain written confirmation before updating invoice metadata through an authorized change.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="non_po_approval",
                    title="Escalate for Non-PO Exception Approval",
                    possible_cause="The purchase may be a legitimate non-PO expense requiring management sign-off.",
                    action="Verify business justification, budget owner approval, and receipt of goods/services.",
                    resolution="Submit for formal exception approval through the approval workflow once documentation is attached.",
                    workflow_action="escalate",
                ),
            ],
            recommended_solution_id=None,
            recommended_solution=(
                "Available records do not contain a matching PO, so no single cause can be confirmed. "
                "First check whether the PO was not imported; otherwise verify non-PO authorization before escalating."
            ),
            required_actions=[
                "Check the procurement system for an unimported PO matching the vendor and amount.",
                "Contact the internal requester to confirm whether a PO was issued or if non-PO approval applies.",
                "Attach verified supporting documentation before routing any approval decision.",
            ],
            required_documents=[
                "Approved purchase order copy (if issued)",
                "Goods receipt note or service delivery confirmation",
                "Written non-PO manager authorization (if no PO exists)",
            ],
            expected_outcome=(
                "No records are altered automatically; once the missing PO is imported or non-PO approval is signed off, the exception can be resolved."
            ),
            confidence_level="low",
            confidence_rationale="No purchase order record was returned by tools; external procurement confirmation is required.",
            insufficient_evidence=True,
        )

    if exception_type == "VENDOR_MISMATCH":
        return ResolutionPlan(
            problem_identification="The vendor name on the source invoice differs from the linked vendor master record.",
            possible_causes=[
                "The difference may be a spelling typo, punctuation difference, or legal suffix abbreviation.",
                "The vendor may operate under a trading name or subsidiary alias.",
                "The invoice may have been linked to the wrong vendor master record.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="verify_vendor_identity_alias",
                    title="Verify Legal Identity and Register Vendor Alias",
                    possible_cause="Both names may belong to the same legal entity (abbreviation or trade name).",
                    action="Compare vendor registration details, tax ID/GSTIN, bank account details, and billing address.",
                    resolution="Link the records or approve a vendor alias only after legal identity is verified.",
                    workflow_action="request_info",
                ),
                ResolutionOption(
                    id="correct_spelling_variation",
                    title="Confirm Spelling Typo in Source Data",
                    possible_cause="A minor clerical or OCR typo may have altered the vendor name on import.",
                    action="Inspect the original invoice document and vendor master profile.",
                    resolution="Escalate for authorized correction of the source metadata once the original document confirms the typo.",
                    workflow_action="escalate",
                ),
                ResolutionOption(
                    id="reject_misattributed_vendor",
                    title="Escalate Potential Misattributed Vendor",
                    possible_cause="The invoice may actually belong to a different legal vendor.",
                    action="Hold payment reconciliation and verify tax ID/bank details to rule out misbilling or fraud.",
                    resolution="Escalate to finance management and do not link records belonging to different legal entities.",
                    workflow_action="escalate",
                ),
            ],
            recommended_solution_id="verify_vendor_identity_alias",
            recommended_solution=(
                "Compare vendor registration details, tax ID/GSTIN, and bank details against the original invoice. "
                "Link records only after confirming both names refer to the same legal vendor."
            ),
            required_actions=[
                "Inspect the original invoice header and vendor master registration details.",
                "Verify tax ID / GSTIN and bank account match before approving any alias or link.",
                "Escalate immediately if identifiers point to two different legal entities.",
            ],
            required_documents=[
                "Original vendor invoice showing legal name and tax ID / GSTIN",
                "Vendor master onboarding form or registration certificate",
                "Verified bank account details",
            ],
            expected_outcome=(
                "Records are never linked automatically; once vendor identity is verified and approved, matching and audit trails remain accurate."
            ),
            confidence_level="medium",
            confidence_rationale="The vendor name discrepancy is verified in persisted records, while legal identity confirmation requires registration documents.",
            insufficient_evidence=False,
        )

    if exception_type == "DATE_GAP":
        return ResolutionPlan(
            problem_identification="The payment date falls outside the configured date tolerance window relative to the invoice date.",
            possible_causes=[
                "The invoice may have extended credit terms or delayed settlement approved by the vendor.",
                "The payment may belong to a different invoice from the same vendor.",
                "Either the invoice date or payment posting date may contain an import error.",
            ],
            possible_solutions=[
                ResolutionOption(
                    id="confirm_delayed_settlement",
                    title="Confirm Delayed Settlement or Extended Terms",
                    possible_cause="Payment may legitimately have occurred later due to agreed payment terms or cash-flow scheduling.",
                    action="Verify the invoice due date, vendor contract terms, and remittance reference.",
                    resolution="Document the verified settlement confirmation and submit for exception review/approval.",
                    workflow_action="propose_adjustment",
                ),
                ResolutionOption(
                    id="verify_payment_allocation",
                    title="Verify Payment Belongs to This Invoice",
                    possible_cause="The payment may actually settle a different invoice with a closer date.",
                    action="Check remittance advice and other invoices for the same vendor.",
                    resolution="Escalate to re-allocate the payment if remittance evidence points to a different invoice.",
                    workflow_action="escalate",
                ),
                ResolutionOption(
                    id="verify_posting_date",
                    title="Check Bank Settlement and Invoice Dates",
                    possible_cause="An incorrect date format or posting date may have been imported.",
                    action="Compare the original invoice PDF and bank statement value date.",
                    resolution="Request an authorized date correction only with supporting bank and invoice proof.",
                    workflow_action="request_info",
                ),
            ],
            recommended_solution_id="confirm_delayed_settlement",
            recommended_solution=(
                "Verify the remittance advice and bank value date to confirm this payment truly settles the linked invoice "
                "before submitting the exception for approval."
            ),
            required_actions=[
                "Check the remittance advice for the exact invoice number paid.",
                "Verify contract payment terms and bank settlement date.",
                "Submit the verified resolution through the approval workflow.",
            ],
            required_documents=[
                "Remittance advice referencing the invoice number",
                "Bank statement showing settlement value date",
                "Vendor contract or invoice payment terms",
            ],
            expected_outcome=(
                "No automatic reconciliation occurs; human approval resolves the date-gap exception once payment allocation is confirmed."
            ),
            confidence_level="medium",
            confidence_rationale="The date gap is verified in persisted records, while settlement intent requires remittance confirmation.",
            insufficient_evidence=False,
        )

    # AMOUNT_MISMATCH (Invoice vs PO) or any other discrepancy
    return ResolutionPlan(
        problem_identification=(
            f"A financial discrepancy was detected across the linked persisted records (variance: {diff})."
            if difference_ref
            else "A discrepancy was detected in the persisted records, but available data is insufficient to confirm a single root cause."
        ),
        possible_causes=[
            "Unit price, quantity, tax, or freight charges may differ between the invoice and the purchase order.",
            "A PO amendment or vendor credit note may not yet be recorded.",
            "One of the source records may contain a data entry or extraction error.",
        ],
        possible_solutions=[
            ResolutionOption(
                id="line_item_verification",
                title="Verify Line Items, Tax, and Freight Against PO",
                possible_cause="Pricing, quantity, or auxiliary charges may explain the variance.",
                action="Compare invoice line items, goods receipt quantities, and approved PO terms.",
                resolution="Submit a verified adjustment or request a vendor credit note for any unapproved variance.",
                workflow_action="propose_adjustment",
            ),
            ResolutionOption(
                id="po_amendment_or_escalation",
                title="Obtain PO Amendment or Escalate",
                possible_cause="An authorized scope or price change may require an updated purchase order.",
                action="Confirm with procurement and the budget owner whether the higher charge was pre-approved.",
                resolution="Escalate for formal PO amendment and management approval before reconciling.",
                workflow_action="escalate",
            ),
            ResolutionOption(
                id="request_vendor_clarification",
                title="Request Supporting Documents from Vendor",
                possible_cause="Insufficient detail in persisted records to confirm the cause of the mismatch.",
                action="Request an itemized invoice breakdown and delivery confirmation from the vendor.",
                resolution="Hold resolution until verified documents establish the correct amount.",
                workflow_action="request_info",
            ),
        ],
        recommended_solution_id=None,
        recommended_solution=(
            "Available persisted records cannot confirm a single cause. Review line-item documents, goods receipts, "
            "and procurement approvals before selecting a resolution for approval."
        ),
        required_actions=[
            "Compare the original invoice line items against the purchase order and goods receipt.",
            "Verify whether any tax, freight, or price change was formally approved.",
            "Select the appropriate resolution path and submit it for approval with supporting evidence.",
        ],
        required_documents=[
            "Original itemized vendor invoice",
            "Approved purchase order and any PO amendment",
            "Goods receipt note or delivery confirmation",
        ],
        expected_outcome=(
            "No records are modified automatically; submitting a chosen resolution routes any financial adjustment through human approval."
        ),
        confidence_level="low",
        confidence_rationale="Persisted records show a discrepancy without line-item or external document proof of the root cause.",
        insufficient_evidence=True,
    )
