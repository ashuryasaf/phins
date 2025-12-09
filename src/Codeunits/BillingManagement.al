codeunit 50101 "PHINS Billing Management"
{
    /// <summary>
    /// Billing Management for PHINS Insurance
    /// Handles policy billing, invoices, payments, and accounting
    /// </summary>

    trigger OnRun()
    begin
        // Entry point for scheduled jobs
    end;

    procedure CreateBill(PolicyID: Code[20]; CustomerID: Code[20]; AmountDue: Decimal; Description: Text): Code[20]
    var
        Bill: Record "PHINS Billing";
        BillIDCounter: Integer;
    begin
        BillIDCounter := GetNextBillID();
        Bill.Init();
        Bill."Bill ID" := 'BILL' + Format(BillIDCounter);
        Bill."Policy ID" := PolicyID;
        Bill."Customer ID" := CustomerID;
        Bill."Bill Date" := Today();
        Bill."Due Date" := CalcDate('<+30D>', Today());
        Bill."Amount Due" := AmountDue;
        Bill.Status := Bill.Status::Outstanding;
        Bill.Description := Description;
        Bill.Insert(true);
        
        exit(Bill."Bill ID");
    end;

    procedure RecordPayment(BillID: Code[20]; PaymentAmount: Decimal; PaymentMethod: Integer)
    var
        Bill: Record "PHINS Billing";
        AccountingMgmt: Codeunit "PHINS Accounting Management";
        AllocationID: Code[20];
    begin
        if Bill.Get(BillID) then begin
            Bill."Amount Paid" += PaymentAmount;
            Bill."Last Payment Date" := Today();
            Bill."Payment Method" := PaymentMethod;
            
            if Bill."Amount Paid" >= Bill."Amount Due" then
                Bill.Status := Bill.Status::Paid
            else if Bill."Amount Paid" > 0 then
                Bill.Status := Bill.Status::Partial;
            
            Bill.Modify();
            
            // Create accounting allocation automatically when payment is recorded
            // Use default risk percentage (can be driven from settings later)
            AllocationID := AccountingMgmt.AllocatePremium(
                BillID,
                Bill."Policy ID",
                Bill."Customer ID",
                PaymentAmount,
                75 // default Risk % (75%)
            );

            // Post allocation to ledger
            AccountingMgmt.PostAllocation(AllocationID);
        end;
    end;

    procedure ApplyLateFee(BillID: Code[20]; LateFeePercentage: Decimal)
    var
        Bill: Record "PHINS Billing";
        LateFee: Decimal;
    begin
        if Bill.Get(BillID) then begin
            if Bill."Due Date" < Today() then begin
                LateFee := Bill."Amount Due" * (LateFeePercentage / 100);
                Bill."Late Fee Applied" := LateFee;
                Bill."Amount Due" += LateFee;
                Bill.Modify();
            end;
        end;
    end;

    procedure GetBillingStatement(CustomerID: Code[20]): Text
    var
        Bill: Record "PHINS Billing";
        TotalDue: Decimal;
        OverdueCount: Integer;
    begin
        Bill.SetRange("Customer ID", CustomerID);
        if Bill.FindSet() then begin
            repeat
                if Bill.Status <> Bill.Status::Paid then
                    TotalDue += Bill."Amount Due";
                if Bill."Due Date" < Today() then
                    OverdueCount += 1;
            until Bill.Next() = 0;
        end;
        
        exit(StrSubstNo('Total Due: %1, Overdue Bills: %2', TotalDue, OverdueCount));
    end;

    local procedure GetNextBillID(): Integer
    var
        Bill: Record "PHINS Billing";
    begin
        if Bill.FindLast() then
            exit(StrToInt(CopyStr(Bill."Bill ID", 5)) + 1)
        else
            exit(1);
    end;
}
