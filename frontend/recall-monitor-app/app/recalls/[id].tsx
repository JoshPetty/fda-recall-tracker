import { useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Link, useLocalSearchParams } from 'expo-router';

import { supabase } from '../../lib/supabase';

type RecallDetail = {
  id: string;
  product_name: string;
  brand: string | null;
  hazard_description: string | null;
  hazard_classification: string | null;
  status: string;
  date_initiated: string | null;
  date_terminated: string | null;
  geographic_scope: string | null;
};

export default function RecallDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [recall, setRecall] = useState<RecallDetail | null>(null);
  const [upcs, setUpcs] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    setIsLoading(true);
    setError(null);

    Promise.all([
      supabase
        .from('recalls')
        .select(
          'id, product_name, brand, hazard_description, hazard_classification, status, date_initiated, date_terminated, geographic_scope'
        )
        .eq('id', id)
        .single(),
      supabase.from('recall_upcs').select('upc').eq('recall_id', id),
    ]).then(([recallResult, upcsResult]) => {
      if (cancelled) return;

      if (recallResult.error) {
        setError(recallResult.error.message);
      } else {
        setRecall(recallResult.data as RecallDetail);
      }

      if (!upcsResult.error) {
        setUpcs(((upcsResult.data ?? []) as { upc: string }[]).map((row) => row.upc));
      }

      setIsLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [id]);

  if (isLoading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator />
      </View>
    );
  }

  if (error || !recall) {
    return (
      <View style={styles.centered}>
        <Text style={styles.body}>{error ?? 'Recall not found.'}</Text>
        <Link href="/recalls" style={styles.back}>
          Back to recalls
        </Link>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Link href="/recalls" style={styles.back}>
        Back to recalls
      </Link>
      <Text style={styles.title}>{recall.product_name}</Text>

      <Field label="Brand" value={recall.brand} />
      <Field label="Hazard" value={recall.hazard_description} />
      <Field label="Hazard classification" value={recall.hazard_classification} />
      <Field label="Status" value={recall.status} />
      <Field label="Date initiated" value={recall.date_initiated} />
      <Field label="Date terminated" value={recall.date_terminated} />
      <Field label="Geographic scope" value={recall.geographic_scope} />

      <Text style={styles.sectionTitle}>UPCs</Text>
      {upcs.length === 0 ? (
        <Text style={styles.body}>No UPCs on file.</Text>
      ) : (
        upcs.map((upc) => (
          <Text key={upc} style={styles.upc}>
            {upc}
          </Text>
        ))
      )}
    </ScrollView>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={styles.fieldValue}>{value ?? 'Not provided'}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    padding: 24,
    gap: 12,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  back: {
    fontSize: 16,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    marginTop: 8,
  },
  body: {
    fontSize: 16,
  },
  field: {
    gap: 2,
  },
  fieldLabel: {
    fontSize: 12,
    color: '#555',
  },
  fieldValue: {
    fontSize: 16,
  },
  upc: {
    fontSize: 15,
    fontFamily: 'monospace',
  },
});
