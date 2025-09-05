'use client'

import { useCallback, useEffect, useMemo } from 'react'
import { useNodes } from 'reactflow'
import { useNodesInteractions } from '@/app/components/workflow/hooks/use-nodes-interactions'
import type { CommonNodeType } from '@/app/components/workflow/types'
import { workflowNodesAction } from '@/app/components/goto-anything/actions/workflow-nodes'
import BlockIcon from '@/app/components/workflow/block-icon'
import { setupNodeSelectionListener } from '@/app/components/workflow/utils/node-navigation'
import { BlockEnum } from '@/app/components/workflow/types'
import { CUSTOM_NOTE_NODE } from '@/app/components/workflow/note-node/constants'
import type { Emoji } from '@/app/components/tools/types'
import type { DataSourceNodeType } from '@/app/components/workflow/nodes/data-source/types'

/**
 * Hook to register RAG pipeline nodes search functionality
 */
export const useRagPipelineSearch = () => {
  const nodes = useNodes()
  const { handleNodeSelect } = useNodesInteractions()

  // Extract tool icon logic for DataSource nodes
  const getToolIcon = useCallback((nodeData: CommonNodeType): string | Emoji | undefined => {
    if (nodeData?.type !== BlockEnum.DataSource) return undefined

    // For DataSource nodes, we need to get the tool icon
    // This is a simplified version - in real implementation you might need
    // to access tool collections from a store or context
    return undefined // Will be enhanced based on actual tool data availability
  }, [])

  const searchableNodes = useMemo(() => {
    const filteredNodes = nodes.filter((node) => {
      if (!node.id || !node.data) return false
      // exclude sticky helpers and note nodes from search
      if (node.type === 'sticky' || node.type === CUSTOM_NOTE_NODE) return false

      const nodeData = node.data as CommonNodeType
      const nodeType = nodeData?.type

      // Exclude internal start/system nodes similar to workflow search
      const internalStartNodes = ['iteration-start', 'loop-start']
      if (internalStartNodes.includes(nodeType)) return false

      // Filter for RAG-specific node types
      const ragNodeTypes = [
        BlockEnum.DataSource,
        BlockEnum.DataSourceEmpty,
        BlockEnum.KnowledgeBase,
        BlockEnum.Tool,
        BlockEnum.Code,
        BlockEnum.HttpRequest,
      ]

      return ragNodeTypes.includes(nodeType)
    })

    return filteredNodes.map((node) => {
      const nodeData = node.data as CommonNodeType | DataSourceNodeType

      return {
        id: node.id,
        title: nodeData?.title || nodeData?.type || 'Untitled',
        type: nodeData?.type || '',
        desc: nodeData?.desc || '',
        blockType: nodeData?.type,
        nodeData,
        toolIcon: getToolIcon(nodeData),
      }
    })
  }, [nodes, getToolIcon])

  // Calculate search score for RAG nodes
  const calculateScore = useCallback((node: {
    title: string;
    type: string;
    desc: string;
  }, searchTerm: string): number => {
    if (!searchTerm) return 1

    const titleMatch = node.title.toLowerCase()
    const typeMatch = node.type.toLowerCase()
    const descMatch = node.desc?.toLowerCase() || ''

    let score = 0

    // Title matching (exact prefix > partial match)
    if (titleMatch.startsWith(searchTerm)) score += 100
    else if (titleMatch.includes(searchTerm)) score += 50

    // Type matching (exact > partial)
    if (typeMatch === searchTerm) score += 80
    else if (typeMatch.includes(searchTerm)) score += 30

    // Description matching (additive)
    if (descMatch.includes(searchTerm)) score += 20

    // RAG-specific scoring bonuses
    if (node.type === BlockEnum.DataSource && searchTerm.includes('data')) score += 40
    if (node.type === BlockEnum.KnowledgeBase && searchTerm.includes('knowledge')) score += 40

    return score
  }, [])

  // Create search function for RAG pipeline nodes (reuses workflow node action @node)
  const searchRagPipelineNodes = useCallback((query: string) => {
    if (!searchableNodes.length) return []

    const searchTerm = query.toLowerCase().trim()

    const results = searchableNodes
      .map((node) => {
        const score = calculateScore(node, searchTerm)

        return score > 0 ? {
          id: node.id,
          title: node.title,
          description: node.desc || node.type,
          type: 'workflow-node' as const,
          path: `#${node.id}`,
          icon: (
            <BlockIcon
              type={node.blockType}
              className="shrink-0"
              size="sm"
              toolIcon={node.toolIcon}
            />
          ),
          metadata: {
            nodeId: node.id,
            nodeData: node.nodeData,
          },
          data: node.nodeData,
          score,
        } : null
      })
      .filter((node): node is NonNullable<typeof node> => node !== null)
      .sort((a, b) => {
        // If no search term, sort alphabetically
        if (!searchTerm) return a.title.localeCompare(b.title)
        // Sort by relevance score (higher score first)
        return (b.score || 0) - (a.score || 0)
      })

    return results
  }, [searchableNodes, calculateScore])

  // Directly set the search function on the workflow nodes action (@node)
  useEffect(() => {
    if (searchableNodes.length > 0) {
      // Set the search function directly on the workflow action
      workflowNodesAction.searchFn = searchRagPipelineNodes
    }

    return () => {
      // Clean up when component unmounts
      workflowNodesAction.searchFn = undefined
    }
  }, [searchableNodes, searchRagPipelineNodes])

  // Set up node selection event listener using the utility function
  useEffect(() => {
    return setupNodeSelectionListener(handleNodeSelect)
  }, [handleNodeSelect])

  return null
}
