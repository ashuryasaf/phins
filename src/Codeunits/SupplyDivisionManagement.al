codeunit 50107 "Supply Division Management"
{
    Caption = 'Supply Division Management';

    procedure RequestOnCall(ProviderID: Code[20])
    var
        SupplyRec: Record "Supply Provider";
        // In a real deployment this would call external APIs or messaging
    begin
        if not SupplyRec.Get(ProviderID) then
            Error('Provider %1 not found', ProviderID);

        if not SupplyRec."Is Active" then
            Error('Provider %1 is not active', ProviderID);

        if not SupplyRec."On Call" then
            Error('Provider %1 is not currently on-call', ProviderID);

        // Placeholder: send notification to provider (email/SMS/webhook)
        Message('Request sent to %1 (%2)', SupplyRec."Display Name", SupplyRec."Contact Email");
    end;

    procedure SearchProvidersByRegion(Region: Text[50]) ProviderList: List of [Code[20]]
    var
        SupplyRec: Record "Supply Provider";
        ProviderIDs: List of [Code[20]];
    begin
        ProviderIDs := ProviderList;
        SupplyRec.SetRange("Is Active", true);
        if SupplyRec.FindSet() then begin
            repeat
                if StrPos(UpperCase(SupplyRec."Regions"), UpperCase(Region)) > 0 then
                    ProviderIDs.Add(SupplyRec."Provider ID");
            until SupplyRec.Next() = 0;
        end;
        exit(ProviderIDs);
    end;

    procedure SyncProviderAvailability(ProviderID: Code[20]) Result: Boolean
    var
        SupplyRec: Record "Supply Provider";
        ok: Boolean;
    begin
        if not SupplyRec.Get(ProviderID) then
            Error('Provider %1 not found', ProviderID);

        if SupplyRec."Webhook URL" = '' then begin
            Message('Provider %1 has no webhook URL configured', SupplyRec."Display Name");
            exit(false);
        end;

        // Attempt to trigger a webhook to request availability sync. In a production
        // scenario this would use robust retry, authentication and error handling.
        ok := TriggerWebhook(ProviderID, '{"action":"sync_availability"}');
        if ok then begin
            SupplyRec."Last Synced" := CurrentDateTime();
            SupplyRec.Modify();
            Message('Availability sync triggered for %1', SupplyRec."Display Name");
        end else
            Message('Failed to trigger availability sync for %1', SupplyRec."Display Name");

        exit(ok);
    end;

    procedure TriggerWebhook(ProviderID: Code[20]; Payload: Text[1024]) Result: Boolean
    var
        SupplyRec: Record "Supply Provider";
        client: HttpClient;
        req: HttpRequestMessage;
        cont: HttpContent;
        resp: HttpResponseMessage;
        headers: HttpHeaders;
        success: Boolean;
    begin
        if not SupplyRec.Get(ProviderID) then
            Error('Provider %1 not found', ProviderID);

        if SupplyRec."Webhook URL" = '' then
            exit(false);

        // Prepare request
        req.SetRequestUri(SupplyRec."Webhook URL");
        req.Method := 'POST';
        cont.WriteFrom(Payload);
        req.Content := cont;
        headers := req.GetHeaders();
        headers.Clear();
        headers.Add('Content-Type', 'application/json');

        // Send request
        if client.Send(req, resp) then begin
            success := resp.IsSuccessStatusCode();
            exit(success);
        end;

        exit(false);
    end;
}
